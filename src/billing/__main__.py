"""`python -m billing` (o el comando `billing`): arranca la app web con Streamlit.

Los argumentos extra se pasan a `streamlit run` (p. ej. `--server.port 8502`).
"""

import sys
from pathlib import Path

from streamlit.web import cli

APP = Path(__file__).resolve().parent / "presentation" / "streamlit" / "app.py"


def main() -> int:
    sys.argv = ["streamlit", "run", str(APP), *sys.argv[1:]]
    return cli.main()


if __name__ == "__main__":
    sys.exit(main())
