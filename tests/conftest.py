import os
import tempfile

# La configuración se lee al importar `billing`, así que el entorno se fija antes y
# tiene prioridad sobre .env: sin Postgres, Keycloak, SMTP ni LLM.
os.environ.update(
    BILLING_DATA_DIR=tempfile.mkdtemp(prefix="billing-test-"),
    BILLING_PERSISTENCE="memory",
    BILLING_MAILER="console",
    BILLING_LLM_PROVIDER="local",
    BILLING_SECRET_KEY="",
)

import pytest  # noqa: E402

from billing.domain.auth import ADMIN, CUSTOMER, Viewer  # noqa: E402
from billing.domain.models import User  # noqa: E402
from billing.infrastructure.persistence.memory.backend import MemoryBackend  # noqa: E402
from billing.infrastructure.persistence.sqlalchemy.backend import SqlAlchemyBackend  # noqa: E402
from billing.infrastructure.storage.local import LocalFileStorage  # noqa: E402

# Usuarios que crea el fixture `backend` (ids = claim `sub` de Keycloak).
ADMIN_ID, ANA_ID, BETO_ID = "sub-admin", "sub-ana", "sub-beto"
ADMIN_VIEWER = Viewer(user_id=ADMIN_ID, role=ADMIN, name="Admin")
ANA_VIEWER = Viewer(user_id=ANA_ID, role=CUSTOMER, name="Ana")
BETO_VIEWER = Viewer(user_id=BETO_ID, role=CUSTOMER, name="Beto")


def pytest_collection_modifyitems(items):
    # El mapeo imperativo de SQLAlchemy instrumenta las entidades para todo el proceso
    # y, desde entonces, el adaptador en memoria deja de funcionar (no asigna ids). En la
    # app solo hay un adaptador; aquí las pruebas en memoria van antes que las de SQL.
    items.sort(key=lambda item: "[sqlite]" in item.nodeid)


@pytest.fixture(params=["memory", "sqlite"])
def backend(request, tmp_path):
    """Persistencia vacía con los usuarios de prueba: en memoria y SQL (SQLite con las
    migraciones de Alembic), para comprobar que ambos adaptadores se comportan igual."""
    if request.param == "memory":
        backend = MemoryBackend()
    else:
        backend = SqlAlchemyBackend(f"sqlite:///{tmp_path / 'billing.db'}")
    backend.init_schema()
    with backend.unit_of_work() as uow:
        uow.users.add(User(id=ADMIN_ID, username="admin", name="Admin", role=ADMIN))
        uow.users.add(User(id=ANA_ID, username="ana", name="Ana", role=CUSTOMER))
        uow.users.add(User(id=BETO_ID, username="beto", name="Beto", role=CUSTOMER))
        uow.commit()
    yield backend
    if request.param == "sqlite":
        backend.engine.dispose()


@pytest.fixture
def uow(backend):
    with backend.unit_of_work() as uow:
        yield uow


@pytest.fixture
def storage(tmp_path):
    return LocalFileStorage(tmp_path / "uploads")


def make_pdf(lines: list[str]) -> bytes:
    """PDF mínimo de una página con texto extraíble (sin dependencias)."""
    text = (
        "BT /F1 12 Tf 50 750 Td 14 TL "
        + " ".join("(" + ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") '" for ln in lines)
        + " ET"
    )
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(text)} >>\nstream\n{text}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = "%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n"
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    return out.encode("latin-1")


def make_email(body: str, *, sender: str = "alertas@notificacionesbancolombia.com", subject: str = "Alerta") -> bytes:
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "ana@billing.example.com"
    msg["Subject"] = subject
    msg["Message-ID"] = "<test@billing.example.com>"
    msg.set_content(body)
    return msg.as_bytes()
