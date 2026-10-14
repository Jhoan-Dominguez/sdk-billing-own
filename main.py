"""Atajo para PyCharm: `python main.py` equivale a `streamlit run streamlit_app.py`."""

import sys
from pathlib import Path

from streamlit.web import cli

if __name__ == "__main__":
    sys.argv = ["streamlit", "run", str(Path(__file__).with_name("streamlit_app.py")), *sys.argv[1:]]
    sys.exit(cli.main())
