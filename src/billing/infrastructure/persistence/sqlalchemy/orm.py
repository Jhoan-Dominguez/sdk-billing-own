"""Mapeo imperativo: las entidades del dominio no heredan de nada de SQLAlchemy."""

from sqlalchemy.orm import registry, relationship

from billing.domain.models import (
    AgentSetting,
    Attachment,
    AuditEntry,
    Category,
    ForecastModel,
    ForecastTrainingRun,
    MailboxConnection,
    Purchase,
    PurchaseItem,
    SecurityConfirmation,
    SpendForecast,
    User,
)
from billing.infrastructure.persistence.sqlalchemy import tables

mapper_registry = registry(metadata=tables.metadata)
_mapped = False


def start_mappers() -> None:
    """Registra los mapeos una sola vez por proceso."""
    global _mapped
    if _mapped:
        return
    mapper_registry.map_imperatively(User, tables.users)
    mapper_registry.map_imperatively(PurchaseItem, tables.purchase_items)
    mapper_registry.map_imperatively(
        Attachment,
        tables.attachments,
        properties={"purchase": relationship(Purchase, back_populates="attachments")},
    )
    mapper_registry.map_imperatively(
        Purchase,
        tables.purchases,
        properties={
            "owner": relationship(User),
            "items": relationship(PurchaseItem, cascade="all, delete-orphan", order_by=tables.purchase_items.c.id),
            "attachments": relationship(Attachment, back_populates="purchase", cascade="all, delete-orphan"),
        },
    )
    mapper_registry.map_imperatively(Category, tables.categories)
    mapper_registry.map_imperatively(SecurityConfirmation, tables.security_confirmations)
    mapper_registry.map_imperatively(AgentSetting, tables.agent_settings)
    mapper_registry.map_imperatively(MailboxConnection, tables.mailbox_connections)
    mapper_registry.map_imperatively(AuditEntry, tables.admin_audit_log)
    mapper_registry.map_imperatively(ForecastTrainingRun, tables.ml_training_runs)
    mapper_registry.map_imperatively(ForecastModel, tables.ml_models)
    mapper_registry.map_imperatively(SpendForecast, tables.spend_forecasts)
    _mapped = True
