# Keycloak con el tema de login "compras" incluido.
# Se construye desde la raíz del repo para poder leer README.md:
#   docker build -f infra/docker/keycloak/Dockerfile .

# El panel derecho del login muestra README.md: se convierte a HTML al construir, así
# la página no depende de JavaScript. <#noparse> evita que FreeMarker interprete
# textos como ${VAR} del README.
FROM python:3.13-slim AS info
RUN pip install --no-cache-dir markdown==3.8
COPY README.md /src/README.md
RUN python -c "import markdown, pathlib; \
html = markdown.markdown(pathlib.Path('/src/README.md').read_text(), extensions=['tables', 'fenced_code']); \
pathlib.Path('/src/info.ftl').write_text('<#noparse>' + html + '</#noparse>')"

FROM quay.io/keycloak/keycloak:26.8
COPY infra/docker/keycloak/themes/compras /opt/keycloak/themes/compras
COPY --from=info /src/info.ftl /opt/keycloak/themes/compras/login/info.ftl
COPY infra/docker/keycloak/realm-compras.json /opt/keycloak/data/import/realm-compras.json
