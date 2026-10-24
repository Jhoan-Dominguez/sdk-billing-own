"""Casos de uso del usuario: sincronización con el login, perfil, preferencias y cuenta."""

import io
import uuid
from collections.abc import Mapping
from datetime import datetime

from PIL import Image, ImageOps, UnidentifiedImageError

from compras.application import categories, imports, purchases
from compras.domain.catalog import PAYMENT_METHODS
from compras.domain.errors import ValidationError
from compras.domain.models import User
from compras.domain.ports.identity import AccountAdmin
from compras.domain.ports.repositories import UnitOfWork
from compras.domain.ports.storage import FileStorage
from compras.domain.values import clean_str, truncate
from compras.settings import DEFAULT_CURRENCY

AVATAR_PREFIX = "avatars/"
AVATAR_SIZE = 256
AVATAR_MAX_BYTES = 5 * 1024 * 1024


def sync_from_claims(uow: UnitOfWork, claims: Mapping, role: str) -> User:
    """Crea o actualiza el usuario con los claims del ID token (en cada inicio de sesión)."""
    user = uow.users.get(claims["sub"])
    if user is None:
        user = User(id=claims["sub"], username=claims["sub"], role=role)
        uow.users.add(user)
    user.username = (claims.get("preferred_username") or claims.get("email") or claims["sub"])[:150]
    user.name = truncate(claims.get("name"), 200)
    user.email = truncate(claims.get("email"), 254)
    user.role = role
    user.last_login_at = datetime.now()
    uow.commit()
    return user


def get(uow: UnitOfWork, user_id: str) -> User | None:
    return uow.users.get(user_id)


def list_users(uow: UnitOfWork, role: str | None = None) -> list[User]:
    return uow.users.list(role)


def currency(user: User | None) -> str:
    return (user.preferred_currency if user else None) or DEFAULT_CURRENCY


def form_defaults(user: User | None) -> dict:
    """Valores por defecto del formulario de compras según las preferencias."""
    return {
        "currency": currency(user),
        "payment_method": user.default_payment_method if user else None,
        "category": user.default_category if user else None,
    }


# --- Perfil -------------------------------------------------------------------


def update_profile(uow: UnitOfWork, account: AccountAdmin, user: User, first_name, last_name) -> None:
    """Valida, guarda el nombre en el proveedor de identidad y luego en la app."""
    first, last = clean_str(first_name), clean_str(last_name)
    if not first or not last:
        raise ValidationError("Nombre y apellido son obligatorios.")
    if len(first) > 100 or len(last) > 100:
        raise ValidationError("Nombre y apellido admiten hasta 100 caracteres.")
    account.update_names(first, last)
    user.name = f"{first} {last}"[:200]
    uow.commit()


def update_preferences(
    uow: UnitOfWork, user: User, *, currency: str | None, payment_method: str | None, category: str | None
) -> None:
    code = clean_str(currency)
    if code and (len(code) != 3 or not code.isalpha()):
        raise ValidationError("La moneda debe ser un código de 3 letras (p. ej. USD).")
    if payment_method and payment_method not in PAYMENT_METHODS:
        raise ValidationError("Método de pago no válido.")
    if category and category not in categories.names(uow, owner_id=user.id):
        raise ValidationError("La categoría no existe.")
    user.preferred_currency = code.upper() if code else None
    user.default_payment_method = payment_method or None
    user.default_category = category or None
    uow.commit()


# --- Avatar -------------------------------------------------------------------


def set_avatar(uow: UnitOfWork, storage: FileStorage, user: User, raw: bytes) -> None:
    """Recorta al centro, reduce a 256×256 y guarda como PNG (sin metadatos EXIF)."""
    if len(raw) > AVATAR_MAX_BYTES:
        raise ValidationError("La imagen supera los 5 MB.")
    try:
        with Image.open(io.BytesIO(raw)) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            img = ImageOps.fit(img, (AVATAR_SIZE, AVATAR_SIZE), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            img.save(out, format="PNG", optimize=True)
    except (UnidentifiedImageError, OSError) as e:
        raise ValidationError("El archivo no es una imagen válida.") from e

    name = f"{uuid.uuid4().hex}.png"
    storage.save(AVATAR_PREFIX + name, out.getvalue())
    old = user.avatar_name
    user.avatar_name = name
    uow.commit()
    if old:
        storage.delete(AVATAR_PREFIX + old)


def remove_avatar(uow: UnitOfWork, storage: FileStorage, user: User) -> None:
    old = user.avatar_name
    user.avatar_name = None
    uow.commit()
    if old:
        storage.delete(AVATAR_PREFIX + old)


def read_avatar(storage: FileStorage, user: User | None) -> bytes | None:
    if not user or not user.avatar_name:
        return None
    try:
        return storage.read(AVATAR_PREFIX + user.avatar_name)
    except FileNotFoundError:
        return None


# --- Cuenta -------------------------------------------------------------------


def delete_account(uow: UnitOfWork, storage: FileStorage, account: AccountAdmin, user: User) -> None:
    """Borra la cuenta en el proveedor de identidad y todo lo del usuario en la app.

    Primero la identidad: si falla, no se pierde nada. Las categorías personales caen
    con el usuario (borrado en cascada del almacenamiento); buzones y confirmaciones
    se borran explícitamente para no depender de las cascadas del motor.
    """
    account.delete()
    for purchase in uow.purchases.by_owner(user.id):
        purchases.delete(uow, storage, purchase)
    for draft in imports.drafts(uow, owner_id=user.id):
        imports.discard_draft(uow, storage, draft)
    remove_avatar(uow, storage, user)
    for mailbox in uow.mailboxes.for_owner(user.id):
        uow.mailboxes.delete(mailbox)
    uow.confirmations.delete_for_user(user.id)
    uow.users.delete(user)
    uow.commit()
