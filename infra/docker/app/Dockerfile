# Imagen de la app web. Se construye desde la raíz del repo:
#   docker build -f infra/docker/app/Dockerfile .
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    BILLING_DATA_DIR=/app/data

WORKDIR /app

# Primero solo lo necesario para instalar dependencias (capa reutilizable en caché).
COPY pyproject.toml README.md ./
COPY src ./src
# Con los SDKs de todos los proveedores LLM (extra "llm"); quita los que no uses.
RUN pip install ".[llm]"

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/data/uploads /app/.streamlit \
    && chown -R app:app /app/data /app/.streamlit

# Configuración de Streamlit (tema), scripts de arranque y de datos de desarrollo.
COPY --chown=app:app .streamlit/config.toml ./.streamlit/config.toml
COPY --chown=app:app scripts ./scripts
COPY --chown=app:app infra/docker/app/entrypoint.sh ./entrypoint.sh

USER app
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"

ENTRYPOINT ["./entrypoint.sh"]
CMD ["python", "-m", "billing", "--server.address=0.0.0.0", "--server.port=8501"]
