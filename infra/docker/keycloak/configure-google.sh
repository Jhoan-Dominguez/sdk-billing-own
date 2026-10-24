#!/usr/bin/env bash
# Configura (o actualiza) Google como proveedor de identidad del realm "billing".
# Con eso el botón "Continuar con Google" del login se activa solo.
#
#   1. En Google Cloud Console > APIs y servicios > Credenciales, crea un
#      "ID de cliente de OAuth" de tipo "Aplicación web" con este URI de redirección:
#        http://localhost:${KEYCLOAK_PORT}/realms/billing/broker/google/endpoint
#   2. Pon GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET en .env
#   3. ./infra/docker/keycloak/configure-google.sh            (o --remove para quitarlo)
set -euo pipefail
cd "$(dirname "$0")/../../.."
# .env aporta los valores, pero las variables ya definidas en el entorno tienen prioridad.
_id=${GOOGLE_CLIENT_ID:-} _secret=${GOOGLE_CLIENT_SECRET:-}
set -a; [ -f .env ] && . ./.env; set +a
GOOGLE_CLIENT_ID=${_id:-${GOOGLE_CLIENT_ID:-}} GOOGLE_CLIENT_SECRET=${_secret:-${GOOGLE_CLIENT_SECRET:-}}
export GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET

if [ "${1:-}" != "--remove" ]; then
  : "${GOOGLE_CLIENT_ID:?Define GOOGLE_CLIENT_ID en .env}"
  : "${GOOGLE_CLIENT_SECRET:?Define GOOGLE_CLIENT_SECRET en .env}"
fi

# Las credenciales viajan como variables de entorno del exec, no como argumentos visibles.
docker compose exec -T -e GOOGLE_CLIENT_ID -e GOOGLE_CLIENT_SECRET -e ACTION="${1:-}" keycloak bash -s <<'EOS'
set -euo pipefail
KC=/opt/keycloak/bin/kcadm.sh
CFG=/tmp/kcadm.config
$KC config credentials --config "$CFG" --server http://localhost:8080 --realm master \
  --user "$KC_BOOTSTRAP_ADMIN_USERNAME" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null

exists() { $KC get identity-provider/instances/google --config "$CFG" -r billing >/dev/null 2>&1; }

if [ "$ACTION" = "--remove" ]; then
  exists && $KC delete identity-provider/instances/google --config "$CFG" -r billing
  echo "Proveedor Google eliminado."
  exit 0
fi

ARGS=(--config "$CFG" -r billing
  -s alias=google -s providerId=google -s displayName=Google -s enabled=true
  -s trustEmail=true -s storeToken=false
  -s "config.clientId=$GOOGLE_CLIENT_ID" -s "config.clientSecret=$GOOGLE_CLIENT_SECRET"
  -s "config.defaultScope=openid profile email" -s config.syncMode=IMPORT)
if exists; then
  $KC update identity-provider/instances/google "${ARGS[@]}"
  echo "Proveedor Google actualizado."
else
  $KC create identity-provider/instances "${ARGS[@]}"
  echo "Proveedor Google creado."
fi
EOS
[ "${1:-}" = "--remove" ] || echo "URI de redirección para Google: http://localhost:${KEYCLOAK_PORT:-8180}/realms/billing/broker/google/endpoint"
