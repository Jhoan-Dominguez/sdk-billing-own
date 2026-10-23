from sqlalchemy.orm import Session, sessionmaker

from compras.infrastructure.persistence.sqlalchemy.repositories import (
    SqlAttachmentRepository,
    SqlCategoryRepository,
    SqlPurchaseRepository,
    SqlUserRepository,
)


class SqlAlchemyUnitOfWork:
    """Implementa compras.domain.ports.repositories.UnitOfWork con una sesión por bloque."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def __enter__(self) -> "SqlAlchemyUnitOfWork":
        self.session = self._session_factory()
        self.users = SqlUserRepository(self.session)
        self.purchases = SqlPurchaseRepository(self.session)
        self.attachments = SqlAttachmentRepository(self.session)
        self.categories = SqlCategoryRepository(self.session)
        return self

    def __exit__(self, *exc) -> None:
        # close() descarta en la base lo no confirmado sin caducar los objetos ya leídos
        # (rollback() los caducaría y no podrían leerse fuera del bloque).
        self.session.close()

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()
