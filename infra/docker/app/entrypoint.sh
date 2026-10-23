#!/bin/sh
set -e
# Streamlit solo lee la configuración OIDC de secrets.toml: se genera desde el entorno.
python scripts/write_secrets.py
exec "$@"
