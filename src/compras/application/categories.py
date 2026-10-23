"""Categorías generales (de todos; las gestiona un admin) y personales (de cada usuario)."""

from compras.domain.catalog import DEFAULT_CATEGORIES, FALLBACK_CATEGORY
from compras.domain.errors import ValidationError
from compras.domain.models import Category
from compras.domain.ports.repositories import UnitOfWork
from compras.domain.values import clean_str


def visible_to(uow: UnitOfWork, *, owner_id: str | None) -> list[Category]:
    """Generales + personales de `owner_id`, con «Otros» al final."""
    categories = uow.categories.visible_to(owner_id)
    return sorted(categories, key=lambda c: (c.name == FALLBACK_CATEGORY, c.name.lower()))


def names(uow: UnitOfWork, *, owner_id: str | None) -> list[str]:
    return [c.name for c in visible_to(uow, owner_id=owner_id)] or list(DEFAULT_CATEGORIES)


def usage(uow: UnitOfWork, *, owner_id: str | None) -> dict[str, int]:
    """Compras por nombre de categoría (de `owner_id`, o de todos si es None)."""
    return uow.purchases.count_by_category(owner_id=owner_id)


def get(uow: UnitOfWork, category_id: int) -> Category | None:
    return uow.categories.get(category_id)


def _validate_name(uow: UnitOfWork, name, owner_id: str | None, exclude_id: int | None = None) -> str:
    name = clean_str(name)
    if not name:
        raise ValidationError("El nombre de la categoría es obligatorio.")
    if len(name) > 50:
        raise ValidationError("El nombre admite hasta 50 caracteres.")
    # Choca con una del mismo ámbito o con una general (las generales las ve todo el mundo).
    if uow.categories.find_name(name, owner_id=owner_id, exclude_id=exclude_id):
        raise ValidationError(f"Ya existe una categoría llamada «{name}».")
    return name


def create(uow: UnitOfWork, name: str, *, owner_id: str | None) -> Category:
    category = Category(name=_validate_name(uow, name, owner_id), owner_id=owner_id)
    uow.categories.add(category)
    uow.commit()
    return category


def _reassign(uow: UnitOfWork, category: Category, new_name: str) -> int:
    """Pasa a `new_name` las compras que usan `category`.

    Personal: las de su dueño. General: las de todos, salvo usuarios con una categoría
    personal del mismo nombre (esas compras son de la personal).
    """
    if category.is_global:
        return uow.purchases.reassign_category(
            category.name,
            new_name,
            owner_id=None,
            exclude_owner_ids=uow.categories.owners_with_personal(category.name),
        )
    return uow.purchases.reassign_category(category.name, new_name, owner_id=category.owner_id)


def rename(uow: UnitOfWork, category: Category, new_name: str) -> int:
    """Renombra la categoría y sus compras. Devuelve cuántas compras cambió."""
    if category.is_protected:
        raise ValidationError(f"«{FALLBACK_CATEGORY}» no se puede renombrar.")
    new_name = _validate_name(uow, new_name, category.owner_id, exclude_id=category.id)
    moved = _reassign(uow, category, new_name)
    uow.users.replace_default_category(category.name, new_name, owner_id=category.owner_id)
    category.name = new_name
    uow.commit()
    return moved


def delete(uow: UnitOfWork, category: Category) -> int:
    """Borra la categoría; sus compras pasan a «Otros». Devuelve cuántas se movieron."""
    if category.is_protected:
        raise ValidationError(f"«{FALLBACK_CATEGORY}» no se puede eliminar.")
    moved = _reassign(uow, category, FALLBACK_CATEGORY)
    uow.users.replace_default_category(category.name, None, owner_id=category.owner_id)
    uow.categories.delete(category)
    uow.commit()
    return moved
