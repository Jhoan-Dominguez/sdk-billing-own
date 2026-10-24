#!/bin/sh
set -e
# Streamlit solo lee la configuración OIDC de secrets.toml: se genera desde el entorno.
# El worker no sirve páginas ni hace login, así que lo omite (COMPRAS_SKIP_SECRETS=1).
if [ "${COMPRAS_SKIP_SECRETS:-0}" != "1" ]; then
    python scripts/write_secrets.py
fi
exec "$@"
