# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Monthly purchase tracker (Spanish UI). Purchases are entered manually, imported from invoice files (images, camera photos, PDFs, `.eml`), or created from bank alert emails (uploaded or read from the user's IMAP mailbox). Every import becomes a draft the user reviews before it becomes a purchase.

Stack: Streamlit (multipage `st.navigation`, OIDC login via `st.login`), SQLAlchemy 2 + Alembic (PostgreSQL by default; any SQLAlchemy URL works), Keycloak 26.8 (login, registration with email verification, TOTP 2FA), LLM providers behind a port (Anthropic, OpenAI/compatible, Gemini, Ollama), SMTP/IMAP. Docker Compose services: `app`, `worker`, `db`, `keycloak`, `pgadmin`, `mailpit` (outgoing mail UI), `greenmail` (test IMAP inbox). Detailed docs live in `docs/` (Spanish); keep them in sync when behaviour changes.

## Commands

- Setup: `make install` (`.venv`, `pip install -e ".[dev]"`, pre-commit hooks). Runtime deps are in `pyproject.toml`; LLM SDKs are extras (`anthropic`, `openai`, `gemini`, `llm`). Don't make extras reference `compras[...]` itself: it hangs pip resolution in Docker.
- Full stack: `make up` (creates `.env` from `.env.example`). App on 8502, Keycloak 8180, pgAdmin 5050, Postgres 5433, Mailpit 8025 (SMTP 1025), GreenMail SMTP 3025 / IMAP 3143. Ports 5432/8081 belong to another project on this machine.
- Local app: `make dev` (db, keycloak, mailpit, greenmail in Docker; `python -m billing` on 8501). Local worker: `make worker`.
- Test data: `make seed` / `make seed-reset`; `make bank-samples` (sends sample bank alerts to GreenMail and connects cliente@'s mailbox); `make sync-once`.
- Lint/format: `make lint` (pre-commit: ruff check + format, line length 120). pre-commit only sees files git knows about (`git add -N` new files).
- Migrations: `make migrate`; new one with `.venv/bin/alembic revision -m "..."` written by hand; `.venv/bin/alembic check` must report no differences.
- Keycloak realm changes: `make keycloak-reimport` (drops the `keycloak` DB; uses `--force-recreate`). Theme/README changes: `make up SERVICE=keycloak`.
- `tests/` still targets the pre-refactor `app` package and is broken; rewriting it is pending.

## Architecture (hexagonal)

`src/billing/`: `domain/` (dataclass entities, rules, `ports/` Protocols) ← `application/` (use cases, receive adapters as arguments) ← `presentation/streamlit/`, `worker/`, `scripts/`. `infrastructure/` implements the ports. `bootstrap.py` is the only place that knows concrete adapters; each swappable service has a registry in its infrastructure package:

- Persistence: `infrastructure/persistence/registry.py` (`BILLING_PERSISTENCE` = `sql` | `memory`). SQL adapter uses imperative mapping (`orm.py`), so domain classes don't inherit from SQLAlchemy. `SqlAlchemyUnitOfWork.__exit__` only calls `session.close()` (a `rollback()` would expire loaded objects). The memory UoW deep-copies state per block. Category uniqueness index differs by dialect (`tables.DIALECT_SPECIFIC_INDEXES`; `migrations/env.py` filters it); migrations use `batch_alter_table` so SQLite works.
- LLM: `infrastructure/llm/registry.py` (`PROVIDERS`). Agents (`application/agents/`: `invoice`, `bank_notification`, prompts in `prompts/*.md`) only see the `LLMClient` port and neutral blocks from `domain/llm.py`. Per-agent provider/model is stored in `agent_settings` (admin UI: Configuración → Agentes IA) and resolved on every call by `bootstrap.agent(name)`; default from `BILLING_LLM_PROVIDER` or the first provider with an API key, else `local` (rules only). Ollama gets `reasoning_effort` from `OLLAMA_REASONING_EFFORT` (default `none`, much faster).
- Extraction: `infrastructure/extraction/`. `LLMInvoiceExtractor` adapts content to model capabilities (`documents.to_blocks`: image downscale, PDF as document, text, or rendered pages) and falls back to regex on any `LLMError`. Uploads never fail because of extraction. Bank alerts: `bank_rules.py` templates (Bancolombia, Davivienda, BBVA, Banco de Bogotá; each `Pattern` has an `example` that must match) first, then the `bank_notification` agent.
- Mail: `infrastructure/mail/` (`SmtpMailer`/`ConsoleMailer` render `EmailContent` with `templates/layout.html`; `ImapGateway` reads read-only with `BODY.PEEK`). The Keycloak email theme mirrors the same layout.

Key rules:

- **Data ownership:** queries on user data take a mandatory `owner_id` keyword; `None` means all users and must come only from `viewer.owner_filter()` (admin). `viewer.can_modify()` allows only the owner. Fetch single rows through use cases (`purchases.get`, `imports.get_draft`, `mailboxes.get`), never directly.
- **Drafts:** an `Attachment` with `purchase_id = NULL` is a draft. `extraction_meta.document_type` is `factura` or `notificacion_bancaria`; confirming a bank draft sets `Purchase.source = "banco"`. Mailbox imports are deduplicated by `(owner_id, message_id)`.
- **Sensitive account actions** (`domain/security.py`, `application/security/`): change password = email link; update/remove 2FA = email + OTP; delete account = email + OTP if enabled. OTP is proven by a Keycloak re-login (`prompt=login`, `max_age=0`) whose ID token must contain `amr` ∋ `otp`. That needs the `amr` client mapper **and** the `amr-pwd`/`amr-otp` authenticator configs in the realm's `authenticationFlows`. Tokens and `state` are stored only as SHA-256; `state` is single-use.
- With `verifyEmail` on, Keycloak 26.8 registration doesn't ask for a password: it is set after the email link.
- The app never sees passwords or TOTP secrets (Keycloak pages only). IMAP passwords are Fernet-encrypted with `BILLING_SECRET_KEY`.
- Money is `Decimal`/`Numeric(12,2)`; totals are grouped per currency and never summed across currencies.
- Deleting purchases, drafts, avatars or accounts must also delete files through `FileStorage` (DB cascades don't touch storage).
- Docker hostname split: browser uses `localhost:8180`, containers use `keycloak:8080` (`KC_HOSTNAME` + `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true`). Don't simplify either away. Containers reach host Ollama at `host.docker.internal`.
- `settings.py` treats empty `.env` values (`VAR=`) as unset for variables with defaults.

## Streamlit conventions

- `app.py` is the gate: login redirect, `Viewer` in `st.session_state["viewer"]`, pages per role (`auth.PAGES_BY_ROLE`). Pages start with `current_viewer()`.
- Configuración tabs live in `presentation/streamlit/components/settings/` (`security`, `account`, `mailboxes`, `agents`); `security.handle_return()` processes `?confirmar=`, `?state&code` and `?kc_action_status` on `/configuracion`.
- Reset forms by bumping a counter in their key; use `flash()` + `st.rerun()` for toasts; other pages request a month with `st.session_state["goto_month"]`.
- Destructive buttons use keys starting with `confirm-delete` (styled red in `assets/styles.css`).
- UI strings, comments and docstrings in Spanish; identifiers in English.

## Repo rules

- Commits: plan them first for user approval; messages in English; small, focused commits; **no co-author trailers**.
- `commands.md` holds the user's local rules and is untracked.
