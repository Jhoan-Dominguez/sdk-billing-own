# Atajos del proyecto. `make` o `make help` lista los comandos.
# Requiere Docker con Compose v2; los comandos de desarrollo local usan .venv/.

COMPOSE ?= docker compose
PYTHON  ?= .venv/bin/python
SERVICE ?=

.DEFAULT_GOAL := help
.PHONY: help env build up down restart logs ps seed seed-reset keycloak-reimport bank-samples mail train \
        install secrets dev worker sync-once migrate test lint format tf-validate

help: ## Muestra esta ayuda
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# --- Docker ---------------------------------------------------------------------

env: ## Crea .env desde .env.example si no existe
	@test -f .env || (cp .env.example .env && echo "Creado .env: cambia las contraseñas 'cambiar-*'")

build: env ## Construye las imágenes (app y Keycloak)
	$(COMPOSE) build $(SERVICE)

up: env ## Levanta todo el stack en segundo plano (construye si hace falta)
	$(COMPOSE) up -d --build $(SERVICE)
	@echo "App: http://localhost:8502 · Keycloak: http://localhost:8180 · pgAdmin: http://localhost:5050 · Mailpit: http://localhost:8025"

down: ## Baja el stack (conserva los datos)
	$(COMPOSE) down

restart: ## Reinicia los servicios (SERVICE=app para uno solo)
	$(COMPOSE) restart $(SERVICE)

logs: ## Sigue los logs (SERVICE=app para uno solo)
	$(COMPOSE) logs -f --tail=100 $(SERVICE)

ps: ## Estado de los servicios
	$(COMPOSE) ps

seed: ## Carga los datos de prueba de desarrollo
	$(COMPOSE) exec app python scripts/seed_dev_data.py

seed-reset: ## Borra y regenera los datos de prueba
	$(COMPOSE) exec app python scripts/seed_dev_data.py --reset

keycloak-reimport: ## Reimporta el realm desde el JSON (borra los usuarios de Keycloak, no las compras)
	$(COMPOSE) stop keycloak
	$(COMPOSE) exec db sh -c 'psql -U "$$POSTGRES_USER" -d postgres -c "DROP DATABASE keycloak" -c "CREATE DATABASE keycloak"'
	$(COMPOSE) up -d --build --force-recreate keycloak

bank-samples: ## Envía alertas bancarias de prueba a GreenMail y conecta el buzón de cliente@ (TO=otro@correo)
	$(COMPOSE) exec app python scripts/send_bank_samples.py --connect $(if $(TO),--to $(TO))

mail: ## Abre la bandeja de Mailpit (correos enviados por la app y Keycloak)
	@echo "Mailpit: http://localhost:8025"; (xdg-open http://localhost:8025 || open http://localhost:8025) >/dev/null 2>&1 || true

# --- Desarrollo local -------------------------------------------------------------

install: ## Crea .venv e instala el paquete con dependencias de desarrollo y hooks
	test -d .venv || python3 -m venv .venv
	$(PYTHON) -m pip install -e ".[dev]"
	.venv/bin/pre-commit install

secrets: env ## Genera .streamlit/secrets.toml (login OIDC) desde .env
	$(PYTHON) scripts/write_secrets.py

dev: env ## Arranca Postgres, Keycloak y correo en Docker y la app en local (http://localhost:8501)
	$(COMPOSE) up -d db keycloak mailpit greenmail
	$(PYTHON) scripts/write_secrets.py
	$(PYTHON) -m billing

worker: ## Ejecuta en local el worker que sincroniza los buzones IMAP
	$(PYTHON) -m billing.worker

sync-once: ## Una sola sincronización de todos los buzones (en el contenedor del worker)
	$(COMPOSE) exec worker python -m billing.worker --once

train: ## Entrena ya los modelos de predicción, incluido el general (en el contenedor del worker)
	$(COMPOSE) exec worker python -m billing.worker --train

migrate: ## Aplica las migraciones pendientes a la base de datos
	.venv/bin/alembic upgrade head

test: ## Ejecuta las pruebas (sin Docker: persistencia en memoria y SQLite)
	$(PYTHON) -m pytest

lint: ## Pasa los hooks de pre-commit (ruff y comprobaciones) a todo el repo
	.venv/bin/pre-commit run --all-files

format: ## Formatea y corrige el código con ruff
	.venv/bin/ruff format src scripts
	.venv/bin/ruff check --fix src scripts

tf-validate: ## Valida la configuración de Terraform (sin credenciales)
	@for env in dev prod; do \
		terraform -chdir=infra/terraform/environments/$$env init -backend=false -input=false >/dev/null && \
		terraform -chdir=infra/terraform/environments/$$env validate || exit 1; \
	done
