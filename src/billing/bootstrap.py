"""Composition root: el único sitio que conoce las implementaciones concretas.

Elige cada adaptador según billing.settings y lo entrega a quien lo pide (la
presentación, el worker y los scripts). Cada servicio tiene su registro en
infrastructure/<servicio>/: para integrar otro motor de base de datos, proveedor LLM,
servidor de correo o almacenamiento se implementa el puerto y se registra allí.
"""

from collections.abc import Callable
from functools import cache

from billing import settings
from billing.application.agents import settings as agent_settings
from billing.application.agents.base import Agent
from billing.application.agents.registry import AGENTS, BANK_NOTIFICATION, INVOICE
from billing.domain.ports.crypto import SecretCipher
from billing.domain.ports.extraction import BankNotificationParser, InvoiceExtractor
from billing.domain.ports.identity import AccountActions, AccountAdmin, Reauthenticator
from billing.domain.ports.mail import MailboxGateway, Mailer
from billing.domain.ports.repositories import UnitOfWork
from billing.domain.ports.storage import FileStorage
from billing.domain.schema import SchemaInfo


class ConfigurationError(RuntimeError):
    pass


# --- Persistencia -------------------------------------------------------------


@cache
def persistence():
    from billing.infrastructure.persistence import registry

    try:
        return registry.create(settings.PERSISTENCE_BACKEND, settings)
    except registry.UnknownBackend as e:
        raise ConfigurationError(str(e)) from e


def unit_of_work() -> UnitOfWork:
    """Una unidad de trabajo nueva: `with bootstrap.unit_of_work() as uow: ...`."""
    return persistence().unit_of_work()


def uow_factory() -> Callable[[], UnitOfWork]:
    return unit_of_work


def init_database() -> None:
    """Prepara el esquema (migraciones) del motor de persistencia elegido."""
    persistence().init_schema()


def describe_schema() -> SchemaInfo | None:
    """Tablas y migraciones del motor elegido (None si no tiene esquema, p. ej. en memoria)."""
    return persistence().describe_schema()


# --- Archivos -----------------------------------------------------------------


@cache
def file_storage() -> FileStorage:
    if settings.STORAGE_BACKEND == "local":
        from billing.infrastructure.storage.local import LocalFileStorage

        return LocalFileStorage(settings.UPLOAD_DIR)
    raise ConfigurationError(f"BILLING_STORAGE desconocido: {settings.STORAGE_BACKEND!r}")


# --- Agentes LLM --------------------------------------------------------------


def llm_catalog():
    """Registro de proveedores LLM (infrastructure/llm/registry.py) para la interfaz de
    administración: qué proveedores hay, si están configurados y sus modelos."""
    from billing.infrastructure.llm import registry

    return registry


def agent_choice(name: str) -> tuple[str, str | None, bool]:
    """(proveedor, modelo, personalizado) con el que se ejecuta el agente `name`."""
    from billing.infrastructure.llm import registry

    provider = registry.default_provider()
    with unit_of_work() as uow:
        return agent_settings.resolve(uow, name, (provider, registry.default_model(provider)))


@cache
def _llm(provider: str, model: str | None):
    from billing.infrastructure.llm import registry

    return registry.build(provider, model)


def agent(name: str) -> Agent | None:
    """El agente con el proveedor elegido; None si es `local` o no está disponible."""
    provider, model, _ = agent_choice(name)
    try:
        llm = _llm(provider, model)
    except Exception:  # SDK no instalado o credenciales inválidas: se usan las reglas
        return None
    return Agent(AGENTS[name], llm) if llm is not None else None


def agent_for(name: str, provider: str, model: str | None) -> Agent | None:
    """El agente con un proveedor/modelo concretos (botón "Probar" de la configuración)."""
    llm = _llm(provider, model)
    return Agent(AGENTS[name], llm) if llm is not None else None


# --- Extracción de facturas y notificaciones bancarias ------------------------


@cache
def invoice_extractor() -> InvoiceExtractor:
    from billing.infrastructure.extraction.extractors import LLMInvoiceExtractor

    return LLMInvoiceExtractor(lambda: agent(INVOICE))


@cache
def bank_parser(*, uploaded: bool = False) -> BankNotificationParser:
    """`uploaded=True` para correos subidos a mano: el agente solo se usa si el
    remitente o el texto son de un banco (los buzones ya filtran por remitente)."""
    from billing.infrastructure.extraction.bank import LLMBankParser

    return LLMBankParser(lambda: agent(BANK_NOTIFICATION), require_bank_sender=uploaded)


# --- Correo -------------------------------------------------------------------


@cache
def mailer() -> Mailer:
    if settings.MAILER_BACKEND == "smtp":
        from billing.infrastructure.mail.smtp import SmtpMailer

        return SmtpMailer(
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            settings.SMTP_FROM,
            user=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            starttls=settings.SMTP_STARTTLS,
            use_ssl=settings.SMTP_SSL,
        )
    if settings.MAILER_BACKEND == "console":
        from billing.infrastructure.mail.console import ConsoleMailer

        return ConsoleMailer()
    raise ConfigurationError(f"BILLING_MAILER desconocido: {settings.MAILER_BACKEND!r}")


@cache
def mailbox_gateway() -> MailboxGateway:
    from billing.infrastructure.mail.imap import ImapGateway

    return ImapGateway()


@cache
def secret_cipher() -> SecretCipher:
    from billing.infrastructure.crypto.fernet import FernetCipher

    return FernetCipher(settings.SECRET_KEY)


# --- Identidad ----------------------------------------------------------------


def identity_admin_configured() -> bool:
    return bool(settings.KEYCLOAK_ADMIN_API_SECRET)


@cache
def _service_token():
    from billing.infrastructure.identity.keycloak import ServiceAccountToken

    return ServiceAccountToken(
        settings.KEYCLOAK_INTERNAL_URL,
        settings.KEYCLOAK_REALM,
        settings.KEYCLOAK_ADMIN_API_CLIENT_ID,
        settings.KEYCLOAK_ADMIN_API_SECRET,
    )


def account_admin(user_id: str) -> AccountAdmin | None:
    """Gestión de la cuenta `user_id` (llamar solo con el usuario autenticado)."""
    if not identity_admin_configured():
        return None
    from billing.infrastructure.identity.keycloak import KeycloakAccountAdmin

    return KeycloakAccountAdmin(_service_token(), settings.KEYCLOAK_INTERNAL_URL, settings.KEYCLOAK_REALM, user_id)


@cache
def account_actions() -> AccountActions:
    from billing.infrastructure.identity.keycloak import KeycloakActions

    return KeycloakActions(
        settings.KEYCLOAK_PUBLIC_URL, settings.KEYCLOAK_REALM, settings.KEYCLOAK_CLIENT_ID, settings.APP_PUBLIC_URL
    )


@cache
def reauthenticator() -> Reauthenticator:
    from billing.infrastructure.identity.keycloak import KeycloakReauthenticator

    return KeycloakReauthenticator(
        settings.KEYCLOAK_PUBLIC_URL,
        settings.KEYCLOAK_INTERNAL_URL,
        settings.KEYCLOAK_REALM,
        settings.KEYCLOAK_CLIENT_ID,
        settings.KEYCLOAK_CLIENT_SECRET,
        settings.APP_PUBLIC_URL,
    )
