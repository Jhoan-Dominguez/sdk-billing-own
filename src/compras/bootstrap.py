"""Composition root: el único sitio que conoce las implementaciones concretas.

Elige cada adaptador según compras.settings y lo entrega a quien lo pide (la
presentación y los scripts). Para integrar otro motor de base de datos, otro
almacenamiento o proveedor de identidad: implementar el puerto en
compras/infrastructure/... y añadir aquí la rama que lo construye.
"""

from collections.abc import Callable
from functools import cache

from compras import settings
from compras.domain.catalog import DEFAULT_CATEGORIES
from compras.domain.ports.extraction import InvoiceExtractor
from compras.domain.ports.identity import AccountActions, AccountAdmin
from compras.domain.ports.repositories import UnitOfWork
from compras.domain.ports.storage import FileStorage


class ConfigurationError(RuntimeError):
    pass


# --- Persistencia -------------------------------------------------------------


@cache
def _uow_factory() -> Callable[[], UnitOfWork]:
    if settings.PERSISTENCE_BACKEND == "sql":
        from compras.infrastructure.persistence.sqlalchemy.database import make_engine, make_session_factory
        from compras.infrastructure.persistence.sqlalchemy.unit_of_work import SqlAlchemyUnitOfWork

        session_factory = make_session_factory(make_engine(settings.DATABASE_URL))
        return lambda: SqlAlchemyUnitOfWork(session_factory)
    raise ConfigurationError(f"COMPRAS_PERSISTENCE desconocido: {settings.PERSISTENCE_BACKEND!r}")


def unit_of_work() -> UnitOfWork:
    """Una unidad de trabajo nueva: `with bootstrap.unit_of_work() as uow: ...`."""
    return _uow_factory()()


def init_database() -> None:
    """Prepara el esquema (migraciones) del adaptador de persistencia elegido."""
    if settings.PERSISTENCE_BACKEND == "sql":
        from compras.infrastructure.persistence.sqlalchemy.database import make_engine, migrate

        engine = make_engine(settings.DATABASE_URL)
        try:
            migrate(engine)
        finally:
            engine.dispose()


# --- Archivos -----------------------------------------------------------------


@cache
def file_storage() -> FileStorage:
    if settings.STORAGE_BACKEND == "local":
        from compras.infrastructure.storage.local import LocalFileStorage

        return LocalFileStorage(settings.UPLOAD_DIR)
    raise ConfigurationError(f"COMPRAS_STORAGE desconocido: {settings.STORAGE_BACKEND!r}")


# --- Extracción de facturas ---------------------------------------------------


@cache
def invoice_extractor() -> InvoiceExtractor:
    from compras.infrastructure.extraction.extractors import ClaudeExtractor, RegexExtractor

    if settings.EXTRACTOR == "claude":
        return ClaudeExtractor(model=settings.CLAUDE_MODEL, categories=DEFAULT_CATEGORIES)
    return RegexExtractor()


# --- Identidad ----------------------------------------------------------------


def identity_admin_configured() -> bool:
    return bool(settings.KEYCLOAK_ADMIN_API_SECRET)


@cache
def _service_token():
    from compras.infrastructure.identity.keycloak import ServiceAccountToken

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
    from compras.infrastructure.identity.keycloak import KeycloakAccountAdmin

    return KeycloakAccountAdmin(_service_token(), settings.KEYCLOAK_INTERNAL_URL, settings.KEYCLOAK_REALM, user_id)


@cache
def account_actions() -> AccountActions:
    from compras.infrastructure.identity.keycloak import KeycloakActions

    return KeycloakActions(
        settings.KEYCLOAK_PUBLIC_URL, settings.KEYCLOAK_REALM, settings.KEYCLOAK_CLIENT_ID, settings.APP_PUBLIC_URL
    )
