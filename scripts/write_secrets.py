"""Genera `.streamlit/secrets.toml` (config de `st.login`) desde variables de entorno.

Streamlit solo lee la configuración OIDC de secrets.toml, así que el contenedor lo
genera al arrancar y en local se ejecuta a mano: `.venv/bin/python scripts/write_secrets.py`.
Lee `.env` si existe; las variables ya definidas en el entorno tienen prioridad.
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = ("AUTH_COOKIE_SECRET", "KEYCLOAK_CLIENT_SECRET")


def main() -> int:
    load_dotenv(ROOT / ".env")
    if missing := [name for name in REQUIRED if not os.environ.get(name)]:
        print(f"Faltan variables de entorno: {', '.join(missing)}", file=sys.stderr)
        return 1

    env = os.environ.get
    realm_url = env("KEYCLOAK_INTERNAL_URL", f"http://localhost:{env('KEYCLOAK_PORT', '8180')}")
    realm = env("KEYCLOAK_REALM", "compras")
    values = {
        "auth": {
            "redirect_uri": env("AUTH_REDIRECT_URI", "http://localhost:8501/oauth2callback"),
            "cookie_secret": env("AUTH_COOKIE_SECRET"),
        },
        "auth.keycloak": {
            "client_id": env("KEYCLOAK_CLIENT_ID", "compras-app"),
            "client_secret": env("KEYCLOAK_CLIENT_SECRET"),
            "server_metadata_url": f"{realm_url}/realms/{realm}/.well-known/openid-configuration",
            # Pedir siempre credenciales: st.logout borra la cookie de Streamlit pero no
            # la sesión SSO de Keycloak, y sin esto se volvería a entrar sin contraseña.
            "client_kwargs": {"scope": "openid profile email", "prompt": "login"},
        },
    }

    lines = []
    for section, entries in values.items():
        lines.append(f"[{section}]")
        for key, value in entries.items():
            if isinstance(value, dict):
                inline = ", ".join(f"{k} = {json.dumps(v)}" for k, v in value.items())
                lines.append(f"{key} = {{ {inline} }}")
            else:
                lines.append(f"{key} = {json.dumps(value)}")
        lines.append("")

    target = ROOT / ".streamlit" / "secrets.toml"
    target.parent.mkdir(exist_ok=True)
    target.write_text("\n".join(lines))
    target.chmod(0o600)
    print(f"Escrito {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
