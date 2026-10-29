"""Exportación y restauración completa de un usuario.

El ZIP contiene:
- `manifest.json`: formato y versión (domain/admin.py), fecha, quién exportó, conteos y
  la lista de archivos con su sha256.
- `data.json`: las filas del usuario tabla por tabla (`users`, `categories`,
  `mailbox_connections`, `purchases`, `purchase_items`, `attachments`) con sus ids y
  claves originales, más su ficha del proveedor de identidad (`identity`).
- `files/<stored_name>` (facturas y correos) y `avatar/<nombre>`.

Al restaurar se insertan filas nuevas y se remapean las claves (ids nuevos), así nunca
chocan con datos existentes. Si la cuenta ya no existe en el proveedor de identidad se
crea de nuevo (con otro id) y se le envía el correo para fijar su contraseña: el
proveedor no exporta contraseñas ni secretos 2FA. Las contraseñas IMAP viajan cifradas y
solo sirven con la misma BILLING_SECRET_KEY; si no, el buzón se restaura desactivado.
No se exportan modelos ni predicciones: se regeneran.
"""

import hashlib
import io
import json
import types
import typing
import uuid
import zipfile
from dataclasses import dataclass, field, fields
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from billing.application import users as user_service
from billing.application.admin import audit
from billing.application.admin.accounts import require_manager
from billing.domain import admin
from billing.domain.auth import ROLES, Viewer
from billing.domain.errors import ValidationError
from billing.domain.models import Attachment, Category, MailboxConnection, Purchase, PurchaseItem, User
from billing.domain.ports.crypto import CipherError, SecretCipher
from billing.domain.ports.identity import (
    ACTION_UPDATE_PASSWORD,
    ACTION_VERIFY_EMAIL,
    IdentityError,
    ManagedAccount,
    UserDirectory,
)
from billing.domain.ports.repositories import UnitOfWork
from billing.domain.ports.storage import FileStorage

MAX_ARCHIVE_ENTRIES = 50_000
MAX_UNCOMPRESSED_BYTES = 2 * 1024**3  # protege de un ZIP que se expande sin medida

TABLES = ("users", "categories", "mailbox_connections", "purchases", "purchase_items", "attachments")
# Relaciones (no columnas) de las entidades.
RELATIONS = {"items", "attachments", "owner", "purchase"}


# --- Serialización ------------------------------------------------------------


def _plain(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):  # incluye datetime
        return value.isoformat()
    return value


def _row(obj, **extra) -> dict:
    row = {f.name: _plain(getattr(obj, f.name, None)) for f in fields(obj) if f.name not in RELATIONS}
    return {**row, **extra}


def _convert(hint, value):
    if value is None:
        return None
    options = typing.get_args(hint) if isinstance(hint, types.UnionType) else (hint,)
    if datetime in options:
        return datetime.fromisoformat(value)
    if date in options:
        return date.fromisoformat(value)
    if Decimal in options:
        return Decimal(value)
    return value


def _entity(cls, row: dict, *, skip: tuple[str, ...] = (), **overrides):
    """Entidad desde una fila exportada; conserva las fechas de alta (campos init=False)."""
    hints = typing.get_type_hints(cls)
    values, later = {}, {}
    for f in fields(cls):
        if f.name in RELATIONS or f.name == "id" or f.name in skip or f.name in overrides:
            continue
        if f.name in row:
            (values if f.init else later)[f.name] = _convert(hints[f.name], row[f.name])
    obj = cls(**values, **overrides)
    for name, value in later.items():
        if value is not None:
            setattr(obj, name, value)
    return obj


# --- Exportación --------------------------------------------------------------


def export_user(
    uow: UnitOfWork, storage: FileStorage, actor: Viewer, user: User, account: ManagedAccount | None
) -> bytes:
    """ZIP con todo lo del usuario. `account` aporta su ficha del proveedor (si responde)."""
    require_manager(actor)
    identity = None
    if account is not None:
        try:
            identity = account.representation()
        except IdentityError:
            identity = None

    purchases = uow.purchases.by_owner(user.id)
    attachments = [att for p in purchases for att in p.attachments] + uow.attachments.drafts(owner_id=user.id)
    tables = {
        "users": [_row(user)],
        "categories": [_row(c) for c in uow.categories.visible_to(user.id) if c.owner_id == user.id],
        "mailbox_connections": [_row(m) for m in uow.mailboxes.for_owner(user.id)],
        "purchases": [_row(p) for p in purchases],
        "purchase_items": [_row(item, purchase_id=p.id) for p in purchases for item in p.items],
        "attachments": [_row(att) for att in attachments],
    }

    buffer = io.BytesIO()
    files, missing = [], []
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        keys = [("files/" + att.stored_name, att.stored_name) for att in attachments]
        if user.avatar_name:
            keys.append(("avatar/" + user.avatar_name, user_service.AVATAR_PREFIX + user.avatar_name))
        for path, key in keys:
            try:
                raw = storage.read(key)
            except FileNotFoundError:
                missing.append(path)
                continue
            archive.writestr(path, raw)
            files.append({"path": path, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        counts = {name: len(rows) for name, rows in tables.items()}
        manifest = {
            "format": admin.EXPORT_FORMAT,
            "version": admin.EXPORT_VERSION,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "exported_by": actor.name,
            "user_id": user.id,
            "email": user.email,
            "counts": counts,
            "files": files,
            "missing_files": missing,
        }
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr(
            "data.json", json.dumps({"identity": identity, "tables": tables}, ensure_ascii=False, indent=2)
        )
    audit.record(uow, actor, admin.EXPORT_USER, target=user, details={"counts": counts, "missing_files": missing})
    return buffer.getvalue()


def export_filename(user: User) -> str:
    who = (user.email or user.username).replace("@", "_at_")
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in who)
    return f"usuario-{safe}-{datetime.now():%Y%m%d-%H%M}.zip"


# --- Lectura del archivo ------------------------------------------------------


@dataclass
class Archive:
    manifest: dict
    data: dict
    files: dict[str, bytes]

    @property
    def tables(self) -> dict[str, list[dict]]:
        return self.data["tables"]

    @property
    def user_row(self) -> dict:
        return self.tables["users"][0]

    @property
    def identity(self) -> dict:
        return self.data.get("identity") or {}

    @property
    def email(self) -> str | None:
        return (self.identity.get("email") or self.user_row.get("email") or "").lower() or None

    @property
    def role(self) -> str:
        roles = self.identity.get("roles") or []
        return next((r for r in ROLES if r in roles), self.user_row.get("role"))


def read_archive(raw: bytes) -> Archive:
    """Valida el ZIP sin extraerlo a disco: solo se leen las rutas que se esperan."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as e:
        raise ValidationError("El archivo no es un ZIP válido.") from e
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ARCHIVE_ENTRIES or sum(i.file_size for i in infos) > MAX_UNCOMPRESSED_BYTES:
            raise ValidationError("El archivo es demasiado grande para restaurarlo.")
        names = {i.filename for i in infos}
        if not {"manifest.json", "data.json"} <= names:
            raise ValidationError("El ZIP no es una exportación de usuario (faltan manifest.json o data.json).")
        try:
            manifest = json.loads(archive.read("manifest.json"))
            data = json.loads(archive.read("data.json"))
        except ValueError as e:
            raise ValidationError("manifest.json o data.json no son JSON válidos.") from e
        if manifest.get("format") != admin.EXPORT_FORMAT:
            raise ValidationError("El ZIP no es una exportación de usuario de esta aplicación.")
        if manifest.get("version") != admin.EXPORT_VERSION:
            raise ValidationError(
                f"Versión de exportación {manifest.get('version')!r} no soportada (se espera {admin.EXPORT_VERSION})."
            )
        tables = data.get("tables") or {}
        if any(not isinstance(tables.get(name), list) for name in TABLES) or len(tables["users"]) != 1:
            raise ValidationError("data.json está incompleto o dañado.")
        files = {}
        for entry in manifest.get("files", []):
            path = entry.get("path", "")
            if path not in names or not path.startswith(("files/", "avatar/")):
                continue
            content = archive.read(path)
            if hashlib.sha256(content).hexdigest() != entry.get("sha256"):
                raise ValidationError(f"El archivo {path} está dañado (sha256 distinto).")
            files[path] = content
    result = Archive(manifest, data, files)
    if not result.email:
        raise ValidationError("La exportación no tiene el correo del usuario.")
    return result


# --- Restauración -------------------------------------------------------------


@dataclass
class RestorePlan:
    """Lo que hará la restauración (vista previa antes de confirmar)."""

    archive: Archive
    account_id: str | None  # cuenta existente en el proveedor con ese correo
    existing_user: bool  # esa cuenta ya entró alguna vez en la app (los datos se suman)
    blocked_reason: str | None = None

    @property
    def counts(self) -> dict[str, int]:
        return {name: len(self.archive.tables[name]) for name in TABLES}


@dataclass
class RestoreResult:
    user_id: str
    created_account: bool
    restored: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def plan_restore(uow: UnitOfWork, directory: UserDirectory, actor: Viewer, raw: bytes) -> RestorePlan:
    require_manager(actor)
    archive = read_archive(raw)
    account_id = directory.find_by_email(archive.email)
    plan = RestorePlan(archive, account_id, existing_user=bool(account_id and uow.users.get(account_id)))
    if uow.users.get(archive.user_row["id"]) is not None:
        plan.blocked_reason = (
            "El usuario exportado todavía existe en la app. Restaurar duplicaría sus datos: elimínalo antes."
        )
    return plan


def restore_user(
    uow: UnitOfWork,
    storage: FileStorage,
    directory: UserDirectory,
    cipher: SecretCipher,
    actor: Viewer,
    raw: bytes,
) -> RestoreResult:
    plan = plan_restore(uow, directory, actor, raw)
    if plan.blocked_reason:
        raise ValidationError(plan.blocked_reason)
    archive = plan.archive
    identity, row = archive.identity, archive.user_row

    created_account = plan.account_id is None
    if created_account:
        first = identity.get("firstName") or (row.get("name") or "").partition(" ")[0] or archive.email
        last = identity.get("lastName") or (row.get("name") or "").partition(" ")[2] or "-"
        user_id = directory.create(
            email=archive.email,
            first_name=first,
            last_name=last,
            role=archive.role,
            email_verified=bool(identity.get("emailVerified")),
        )
    else:
        user_id = plan.account_id

    result = RestoreResult(user_id=user_id, created_account=created_account)
    saved_keys: list[str] = []
    try:
        state = _restore_rows(uow, storage, cipher, archive, user_id, result, saved_keys)
    except Exception:
        for key in saved_keys:
            storage.delete(key)
        _undo(uow, user_id, plan.existing_user)
        if created_account:
            try:
                directory.account(user_id).delete()
            except IdentityError:
                result.warnings.append("No se pudo borrar la cuenta recién creada en el proveedor.")
        raise

    if created_account:
        actions = [ACTION_UPDATE_PASSWORD] + ([] if identity.get("emailVerified") else [ACTION_VERIFY_EMAIL])
        try:
            directory.account(user_id).send_actions_email(actions)
        except IdentityError as e:
            result.warnings.append(f"No se pudo enviar el correo para fijar la contraseña: {e}")
    audit.record(
        uow,
        actor,
        admin.RESTORE_USER,
        target_id=user_id,
        target_label=archive.email,
        details={
            "source_user_id": row["id"],
            "created_account": created_account,
            "restored": result.restored,
            "warnings": result.warnings,
            **state,
        },
    )
    return result


def _undo(uow: UnitOfWork, user_id: str, existing_user: bool) -> None:
    """Deshace la primera fase si la segunda falló (la base no tiene transacción entre ambas)."""
    uow.rollback()
    if not existing_user and (user := uow.users.get(user_id)):
        for mailbox in uow.mailboxes.for_owner(user_id):
            uow.mailboxes.delete(mailbox)
        uow.users.delete(user)  # categorías en cascada
        uow.commit()


def _restore_rows(
    uow: UnitOfWork,
    storage: FileStorage,
    cipher: SecretCipher,
    archive: Archive,
    user_id: str,
    result: RestoreResult,
    saved_keys: list[str],
) -> dict:
    tables, row = archive.tables, archive.user_row

    def save_file(path: str, suffix: str, prefix: str = "") -> str | None:
        content = archive.files.get(path)
        if content is None:
            return None
        name = f"{uuid.uuid4().hex}{suffix}"
        storage.save(prefix + name, content)
        saved_keys.append(prefix + name)
        return name

    # Fase 1: usuario, categorías personales y buzones (los adjuntos necesitan el id del buzón).
    user = uow.users.get(user_id)
    if user is None:
        avatar = save_file(f"avatar/{row.get('avatar_name')}", ".png", user_service.AVATAR_PREFIX)
        user = _entity(User, row, skip=("disabled_at",), id=user_id, role=archive.role, avatar_name=avatar)
        uow.users.add(user)
    restored = {name: 0 for name in TABLES}
    restored["users"] = 1
    for category_row in tables["categories"]:
        if uow.categories.find_name(category_row["name"], owner_id=user_id) is None:
            uow.categories.add(_entity(Category, category_row, owner_id=user_id))
            restored["categories"] += 1
    mailboxes: dict[int, MailboxConnection] = {}
    disabled_mailboxes = 0
    for mailbox_row in tables["mailbox_connections"]:
        mailbox = _entity(MailboxConnection, mailbox_row, owner_id=user_id)
        try:
            cipher.decrypt(mailbox.password_encrypted)
        except CipherError:
            mailbox.enabled = False
            mailbox.last_error = "La contraseña no se pudo recuperar al restaurar; vuelve a ingresarla."
            disabled_mailboxes += 1
        uow.mailboxes.add(mailbox)
        mailboxes[mailbox_row["id"]] = mailbox
        restored["mailbox_connections"] += 1
    uow.commit()
    if disabled_mailboxes:
        result.warnings.append(
            f"{disabled_mailboxes} buzón(es) quedaron desactivados: hay que reingresar la contraseña."
        )

    # Fase 2: compras con sus líneas y adjuntos, y los borradores.
    def attachment(att_row: dict, *, draft: bool) -> Attachment | None:
        stored = save_file(f"files/{att_row['stored_name']}", Path(att_row["stored_name"]).suffix)
        if stored is None:
            result.warnings.append(f"Falta el archivo de «{att_row['original_name']}»; no se restauró.")
            return None
        message_id = att_row.get("message_id")
        if message_id and uow.attachments.by_message_id(message_id, owner_id=user_id):
            if draft:  # ese correo ya está importado en la cuenta
                storage.delete(stored)
                saved_keys.remove(stored)
                return None
            message_id = None
        old_mailbox = mailboxes.get(att_row.get("mailbox_id"))
        return _entity(
            Attachment,
            att_row,
            skip=("purchase_id",),
            owner_id=user_id,
            stored_name=stored,
            message_id=message_id,
            mailbox_id=old_mailbox.id if old_mailbox else None,
        )

    items_by_purchase: dict[int, list[dict]] = {}
    for item_row in tables["purchase_items"]:
        items_by_purchase.setdefault(item_row["purchase_id"], []).append(item_row)
    atts_by_purchase: dict[int | None, list[dict]] = {}
    for att_row in tables["attachments"]:
        atts_by_purchase.setdefault(att_row.get("purchase_id"), []).append(att_row)

    for purchase_row in tables["purchases"]:
        purchase = _entity(Purchase, purchase_row, owner_id=user_id)
        for item_row in items_by_purchase.get(purchase_row["id"], []):
            purchase.items.append(_entity(PurchaseItem, item_row, skip=("purchase_id",)))
            restored["purchase_items"] += 1
        for att_row in atts_by_purchase.get(purchase_row["id"], []):
            if (att := attachment(att_row, draft=False)) is not None:
                purchase.attachments.append(att)
                restored["attachments"] += 1
        uow.purchases.add(purchase)
        restored["purchases"] += 1
    for att_row in atts_by_purchase.get(None, []):
        if (att := attachment(att_row, draft=True)) is not None:
            uow.attachments.add(att)
            restored["attachments"] += 1
    uow.commit()
    result.restored = restored
    return {"disabled_mailboxes": disabled_mailboxes}
