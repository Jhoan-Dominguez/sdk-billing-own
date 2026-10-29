from sqlalchemy.orm import Session, sessionmaker

from billing.infrastructure.persistence.sqlalchemy.repositories import (
    SqlAgentSettingRepository,
    SqlAttachmentRepository,
    SqlAuditRepository,
    SqlCategoryRepository,
    SqlForecastModelRepository,
    SqlForecastRunRepository,
    SqlMailboxRepository,
    SqlPurchaseRepository,
    SqlSecurityConfirmationRepository,
    SqlUserRepository,
)


class SqlAlchemyUnitOfWork:
    """Implementa billing.domain.ports.repositories.UnitOfWork con una sesión por bloque."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def __enter__(self) -> "SqlAlchemyUnitOfWork":
        self.session = self._session_factory()
        self.users = SqlUserRepository(self.session)
        self.purchases = SqlPurchaseRepository(self.session)
        self.attachments = SqlAttachmentRepository(self.session)
        self.categories = SqlCategoryRepository(self.session)
        self.confirmations = SqlSecurityConfirmationRepository(self.session)
        self.agent_settings = SqlAgentSettingRepository(self.session)
        self.mailboxes = SqlMailboxRepository(self.session)
        self.audit_log = SqlAuditRepository(self.session)
        self.forecast_models = SqlForecastModelRepository(self.session)
        self.forecast_runs = SqlForecastRunRepository(self.session)
        return self

    def __exit__(self, *exc) -> None:
        # close() descarta en la base lo no confirmado sin caducar los objetos ya leídos
        # (rollback() los caducaría y no podrían leerse fuera del bloque).
        self.session.close()

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()
