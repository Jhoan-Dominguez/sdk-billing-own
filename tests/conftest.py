import os
import tempfile

# La configuración se lee al importar `app`, así que el entorno se fija antes.
_tmp = tempfile.mkdtemp(prefix="compras-test-")
os.environ["COMPRAS_DATA_DIR"] = _tmp
os.environ["COMPRAS_EXTRACTOR"] = "local"

import pytest  # noqa: E402

from app.db import Base, SessionLocal, engine, init_db  # noqa: E402


@pytest.fixture
def db():
    """Base de datos vacía para cada test."""
    init_db()
    with SessionLocal() as session:
        yield session
    Base.metadata.drop_all(engine)


def make_pdf(lines: list[str]) -> bytes:
    """PDF mínimo de una página con texto extraíble (sin dependencias)."""
    text = "BT /F1 12 Tf 50 750 Td 14 TL " + " ".join(
        "(" + ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") '" for ln in lines
    ) + " ET"
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
