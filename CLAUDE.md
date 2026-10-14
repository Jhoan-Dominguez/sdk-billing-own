# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Monthly purchase tracker (Spanish UI). Purchases are entered manually or imported from invoice files (images, camera photos, PDFs, `.eml` emails); imported files are kept on disk and converted into a draft the user reviews before it becomes a purchase.

Stack: Streamlit (multipage via `st.navigation`), SQLAlchemy 2.0 on SQLite, pypdf, Anthropic SDK for invoice extraction. `streamlit[pdf]` is required for `st.pdf`.

## Commands

- Setup: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
- Run (http://localhost:8501): `.venv/bin/streamlit run streamlit_app.py`. `.venv/bin/python main.py` does the same and forwards extra args.
- Tests: `.venv/bin/python -m pytest`
- Single test: `.venv/bin/python -m pytest tests/test_ui.py::test_summary_edit_and_delete`

## Configuration (env vars, read once in `app/config.py` at import)

- `COMPRAS_DATA_DIR` (default `./data`): holds `compras.db` and `uploads/`.
- `COMPRAS_DATABASE_URL`: overrides the SQLite URL.
- `COMPRAS_EXTRACTOR`: `claude` or `local`. Defaults to `claude` only if `ANTHROPIC_API_KEY` is set.
- `COMPRAS_CLAUDE_MODEL` (default `claude-opus-5-5`), `COMPRAS_MONEDA` (default currency).

## Architecture

Layers: `app/` holds UI-agnostic domain code (models, services, extraction) plus `app/ui.py` (shared Streamlit widgets). `app_pages/*.py` are the Streamlit pages and are registered in `streamlit_app.py`. Keep DB and business logic out of the pages so they stay testable without Streamlit.

- **Import flow (draft → purchase):** `services.store_upload` writes the file to `UPLOAD_DIR` under a UUID name, runs `extraction.extract`, and stores an `Attachment` with `purchase_id = NULL` and the extracted `InvoiceData` in its `extracted` JSON column. An attachment with no `purchase_id` *is* a pending draft; there's no separate draft table. `services.confirm_draft` creates the `Purchase` (with `source` = attachment kind) and links the attachment.
- **Extraction (`app/extraction.py`):** files are normalized into a list of `Part`s; emails are split into header, body text and their PDF/image attachments. The `claude` extractor sends the parts as image/document/text blocks to `client.beta.messages.parse(output_format=InvoiceData)` with server-side refusal fallbacks. The `local` extractor uses only text (pypdf + email body) plus regexes, and it can't read images or scanned PDFs. Any extractor exception falls back to local regexes and sets `extraction_error`, so uploads never fail because extraction failed.
- **Purchase form:** `ui.purchase_form(key, values, items)` (an `st.form` with `st.data_editor` for line items) returns typed `(values, items)` on submit. Every create/edit/confirm path then calls `services.apply_values`, which validates, converts to `Decimal` (also handles pandas NaN and `,` decimals), drops blank editor rows, and computes the total from lines or subtotal+tax when it's blank.
- **Streamlit state conventions:**
  - Widget state is keyed. To reset a form after saving, bump a counter that is part of its key (`new_purchase_form`, `upload_no`).
  - A widget's value can't be changed after the widget is created in the same run. Other pages therefore request a month change via `st.session_state["goto_month"]`, which `resumen.py` copies into the `month` selectbox key before rendering it.
  - The edit dialog stays open through `st.session_state["editing"]` and isn't tied to the button's click value, so it survives full reruns.
  - Use `ui.flash()` + `st.rerun()` for post-action toasts (rendered by `show_flash()` in `streamlit_app.py`).
- **Sessions:** pages open `SessionLocal()` in a `with` block and render ORM objects inside it, because relationships are lazy-loaded.
- **Money:** `Numeric(12,2)` / `Decimal` in the DB, converted to float only for display and charts. Totals are always grouped per currency (`services.totals_by`) and never summed across currencies.
- **Schema:** tables come from `Base.metadata.create_all` (`ui.ensure_db`, cached with `st.cache_resource`). There are no migrations yet, so changing a model requires deleting `data/compras.db` or adding Alembic.
- Deleting a purchase must also delete its files on disk (`services.delete_purchase`); DB cascades don't touch the filesystem.

## Tests

- `tests/conftest.py` sets `COMPRAS_DATA_DIR` to a temp dir and forces `COMPRAS_EXTRACTOR=local` **before** importing `app`. Keep that ordering. The `db` fixture gives each test an empty DB, and `make_pdf()` builds text PDFs without dependencies.
- UI tests use `streamlit.testing.v1.AppTest` with absolute paths to the page files. AppTest can't select `st.dataframe` rows, so `select_first_row` in `tests/test_ui.py` injects the selection widget state by patching `ElementTree.get_widget_states`. That helper relies on Streamlit internals and may need updating after Streamlit upgrades.
- The Claude extractor is tested by monkeypatching `anthropic.Anthropic`, so tests make no network calls.
