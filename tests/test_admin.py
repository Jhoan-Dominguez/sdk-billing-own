import io
import json
import zipfile
from datetime import date, datetime, timedelta

import pytest

from billing.application import imports
from billing.application import purchases as purchase_service
from billing.application import users as user_service
from billing.application.admin import accounts, audit, backup, system
from billing.application.forecasting import models as model_service
from billing.domain import admin, forecasting
from billing.domain.auth import ADMIN, CUSTOMER
from billing.domain.errors import PermissionDenied, ValidationError
from billing.domain.models import Category, ForecastModel, ForecastTrainingRun, MailboxConnection
from billing.infrastructure.extraction.bank import RuleBankParser
from billing.infrastructure.extraction.extractors import RegexExtractor
from tests.conftest import ADMIN_ID, ADMIN_VIEWER, ANA_ID, ANA_VIEWER, BETO_ID, FakeCipher, make_pdf

VALUES = {
    "purchase_date": date(2026, 10, 5),
    "vendor": "Tienda",
    "currency": "usd",
    "category": "Supermercado",
    "total": "10",
}


def upload(uow, storage, owner_id=ANA_ID, name="factura.pdf"):
    raw = make_pdf(["Ferreteria Central", "Fecha 2026-10-05", "Total 45.90"])
    return imports.store_upload(
        uow, storage, RegexExtractor(), name, None, raw, owner_id=owner_id, bank_parser=RuleBankParser()
    )


def populate_ana(uow, storage, cipher):
    """Ana con una compra (líneas + factura), un borrador, una categoría propia, un buzón y avatar."""
    items = [{"description": "Pan", "quantity": 2, "unit_price": "1.25"}]
    purchase_service.create(uow, {**VALUES, "total": None}, items, owner_id=ANA_ID)  # total = 2.50
    draft = upload(uow, storage)
    imports.confirm_draft(uow, draft, {**VALUES, "vendor": "Ferretería", "total": "45.90"}, [])
    upload(uow, storage, name="pendiente.pdf")
    uow.categories.add(Category(name="Mascotas", owner_id=ANA_ID))
    uow.mailboxes.add(
        MailboxConnection(
            owner_id=ANA_ID, host="imap.example.com", port=993, username="ana", password_encrypted=cipher.encrypt("s3")
        )
    )
    uow.commit()
    user_service.set_avatar(uow, storage, uow.users.get(ANA_ID), make_png())


def make_png() -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(out, format="PNG")
    return out.getvalue()


# --- Permisos y cuentas ---------------------------------------------------------------


def test_only_managers_use_admin_cases(uow, directory):
    with pytest.raises(PermissionDenied):
        accounts.overview(uow, ANA_VIEWER)
    with pytest.raises(PermissionDenied):
        accounts.block(uow, directory, ANA_VIEWER, uow.users.get(BETO_ID))


def test_overview_counts_usage_without_amounts(uow, storage, directory):
    purchase_service.create(uow, VALUES, [], owner_id=ANA_ID)
    upload(uow, storage)
    rows = {r.user.id: r for r in accounts.overview(uow, ADMIN_VIEWER, directory.statuses())}
    assert rows[ANA_ID].purchases == 1 and rows[ANA_ID].drafts == 1 and rows[ANA_ID].files == 1
    assert rows[ANA_ID].bytes > 0 and rows[ANA_ID].identity["enabled"]
    assert rows[BETO_ID].purchases == 0


def test_overview_flags_accounts_missing_in_identity_provider(uow, directory):
    directory.accounts[BETO_ID].deleted = True  # borrada desde la consola de Keycloak
    rows = {r.user.id: r for r in accounts.overview(uow, ADMIN_VIEWER, directory.statuses())}
    assert rows[BETO_ID].identity_missing and not rows[ANA_ID].identity_missing
    # Sin estados (Keycloak no respondió) no se marca ninguna.
    assert not any(r.identity_missing for r in accounts.overview(uow, ADMIN_VIEWER, None))


def test_block_and_unblock(backend, directory):
    with backend.unit_of_work() as uow:
        accounts.block(uow, directory, ADMIN_VIEWER, uow.users.get(ANA_ID))
    with backend.unit_of_work() as uow:
        assert uow.users.get(ANA_ID).is_disabled
        assert not directory.accounts[ANA_ID].enabled and directory.accounts[ANA_ID].logouts == 1
        accounts.unblock(uow, directory, ADMIN_VIEWER, uow.users.get(ANA_ID))
    with backend.unit_of_work() as uow:
        assert not uow.users.get(ANA_ID).is_disabled and directory.accounts[ANA_ID].enabled
        assert [e.action for e in audit.entries(uow)] == [admin.UNBLOCK_USER, admin.BLOCK_USER]


def test_admin_cannot_act_on_itself(uow, directory):
    with pytest.raises(PermissionDenied):
        accounts.block(uow, directory, ADMIN_VIEWER, uow.users.get(ADMIN_ID))
    with pytest.raises(PermissionDenied):
        accounts.change_role(uow, directory, ADMIN_VIEWER, uow.users.get(ADMIN_ID), CUSTOMER)


def test_change_role_and_support_actions(uow, directory):
    ana = uow.users.get(ANA_ID)
    accounts.change_role(uow, directory, ADMIN_VIEWER, ana, ADMIN)
    assert ana.role == ADMIN and directory.accounts[ANA_ID].role == ADMIN
    assert directory.accounts[ANA_ID].logouts == 1  # el rol nuevo aplica al volver a entrar
    with pytest.raises(ValidationError):
        accounts.change_role(uow, directory, ADMIN_VIEWER, ana, "superuser")

    beto = uow.users.get(BETO_ID)
    directory.accounts[BETO_ID].otp = True
    accounts.force_password_change(uow, directory, ADMIN_VIEWER, beto)
    accounts.resend_verification(uow, directory, ADMIN_VIEWER, beto)
    assert accounts.remove_otp(uow, directory, ADMIN_VIEWER, beto) == 1
    assert directory.accounts[BETO_ID].emails == [["UPDATE_PASSWORD"], ["VERIFY_EMAIL"]]
    actions = [e.action for e in audit.entries(uow, target_user_id=BETO_ID)]
    assert actions == [admin.REMOVE_OTP, admin.RESEND_VERIFICATION, admin.FORCE_PASSWORD_CHANGE]


def test_invite_creates_account_and_sends_email(uow, directory):
    user_id = accounts.invite(
        uow,
        directory,
        ADMIN_VIEWER,
        email=" Nuevo@Example.com ",
        first_name="Nuevo",
        last_name="Cliente",
        role=CUSTOMER,
    )
    account = directory.accounts[user_id]
    assert account.email == "nuevo@example.com" and account.emails == [["VERIFY_EMAIL", "UPDATE_PASSWORD"]]
    with pytest.raises(ValidationError, match="Ya existe"):
        accounts.invite(
            uow, directory, ADMIN_VIEWER, email="ana@example.com", first_name="A", last_name="B", role=CUSTOMER
        )


def test_delete_removes_data_and_keeps_audit(backend, storage, directory):
    with backend.unit_of_work() as uow:
        draft = upload(uow, storage)
        key = draft.stored_name
        accounts.delete(uow, storage, directory, ADMIN_VIEWER, uow.users.get(ANA_ID))
    with backend.unit_of_work() as uow:
        assert uow.users.get(ANA_ID) is None and directory.accounts[ANA_ID].deleted
        assert imports.drafts(uow, owner_id=ANA_ID) == []
        entry = audit.entries(uow)[0]
        assert entry.action == admin.DELETE_USER and entry.target_label == "Ana"  # sin correo: su nombre
    with pytest.raises(FileNotFoundError):
        storage.read(key)


# --- Exportación y restauración -----------------------------------------------------


def test_export_delete_restore_round_trip(backend, storage, directory):
    cipher = FakeCipher()
    with backend.unit_of_work() as uow:
        uow.users.get(ANA_ID).email = "ana@example.com"
        uow.commit()
        populate_ana(uow, storage, cipher)
        raw = backup.export_user(uow, storage, ADMIN_VIEWER, uow.users.get(ANA_ID), directory.account(ANA_ID))

    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        data = json.loads(archive.read("data.json"))
    assert manifest["format"] == admin.EXPORT_FORMAT and manifest["version"] == admin.EXPORT_VERSION
    assert manifest["counts"] == {
        "users": 1,
        "categories": 1,
        "mailbox_connections": 1,
        "purchases": 2,
        "purchase_items": 1,
        "attachments": 2,
    }
    assert len(manifest["files"]) == 3  # factura, borrador y avatar
    assert data["identity"]["email"] == "ana@example.com"

    with backend.unit_of_work() as uow:
        # Mientras el usuario exista, restaurar duplicaría sus datos.
        with pytest.raises(ValidationError, match="todavía existe"):
            backup.restore_user(uow, storage, directory, cipher, ADMIN_VIEWER, raw)
        accounts.delete(uow, storage, directory, ADMIN_VIEWER, uow.users.get(ANA_ID))

    with backend.unit_of_work() as uow:
        plan = backup.plan_restore(uow, directory, ADMIN_VIEWER, raw)
        assert plan.account_id is None and plan.blocked_reason is None
        result = backup.restore_user(uow, storage, directory, cipher, ADMIN_VIEWER, raw)

    assert result.created_account and result.user_id != ANA_ID
    assert result.restored["purchases"] == 2 and result.restored["attachments"] == 2
    assert directory.accounts[result.user_id].emails == [["UPDATE_PASSWORD"]]
    with backend.unit_of_work() as uow:
        new_id = result.user_id
        user = uow.users.get(new_id)
        assert user.email == "ana@example.com" and user.role == CUSTOMER
        assert user_service.read_avatar(storage, user) is not None
        purchases = sorted(uow.purchases.by_owner(new_id), key=lambda p: p.vendor)
        assert [p.vendor for p in purchases] == ["Ferretería", "Tienda"]
        assert str(purchases[1].total) == "2.50" and purchases[1].items[0].description == "Pan"
        assert storage.read(purchases[0].attachments[0].stored_name).startswith(b"%PDF")
        assert len(imports.drafts(uow, owner_id=new_id)) == 1
        assert "Mascotas" in [c.name for c in uow.categories.visible_to(new_id) if c.owner_id == new_id]
        mailbox = uow.mailboxes.for_owner(new_id)[0]
        assert mailbox.enabled and cipher.decrypt(mailbox.password_encrypted) == "s3"
        assert audit.entries(uow)[0].action == admin.RESTORE_USER


def test_restore_with_other_secret_key_disables_mailboxes(backend, storage, directory):
    with backend.unit_of_work() as uow:
        populate_ana(uow, storage, FakeCipher("old"))
        raw = backup.export_user(uow, storage, ADMIN_VIEWER, uow.users.get(ANA_ID), directory.account(ANA_ID))
        accounts.delete(uow, storage, directory, ADMIN_VIEWER, uow.users.get(ANA_ID))
        result = backup.restore_user(uow, storage, directory, FakeCipher("new"), ADMIN_VIEWER, raw)
    with backend.unit_of_work() as uow:
        mailbox = uow.mailboxes.for_owner(result.user_id)[0]
        assert not mailbox.enabled and "contraseña" in mailbox.last_error
    assert any("buzón" in w for w in result.warnings)


def test_restore_into_existing_account(backend, storage, directory):
    """Si ya hay una cuenta con ese correo (p. ej. se registró de nuevo), los datos van a ella."""
    with backend.unit_of_work() as uow:
        purchase_service.create(uow, VALUES, [], owner_id=ANA_ID)
        raw = backup.export_user(uow, storage, ADMIN_VIEWER, uow.users.get(ANA_ID), directory.account(ANA_ID))
        accounts.delete(uow, storage, directory, ADMIN_VIEWER, uow.users.get(ANA_ID))
        new_id = directory.create(email="ana@example.com", first_name="Ana", last_name="Uno", role=CUSTOMER)
        result = backup.restore_user(uow, storage, directory, FakeCipher(), ADMIN_VIEWER, raw)
    assert result.user_id == new_id and not result.created_account
    with backend.unit_of_work() as uow:
        assert len(uow.purchases.by_owner(new_id)) == 1


def test_restore_rejects_foreign_or_damaged_archives(uow, directory):
    with pytest.raises(ValidationError, match="ZIP"):
        backup.plan_restore(uow, directory, ADMIN_VIEWER, b"no es un zip")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format": admin.EXPORT_FORMAT, "version": 99}))
        archive.writestr("data.json", "{}")
    with pytest.raises(ValidationError, match="no soportada"):
        backup.plan_restore(uow, directory, ADMIN_VIEWER, buffer.getvalue())


# --- Estado, métricas y retención ---------------------------------------------------


def test_purge_stale_drafts(backend, storage):
    with backend.unit_of_work() as uow:
        old = upload(uow, storage)
        old.uploaded_at = datetime.now() - timedelta(days=90)
        uow.commit()
        upload(uow, storage, owner_id=BETO_ID)  # reciente: se conserva
        assert system.stale_drafts(uow, ADMIN_VIEWER, older_than_days=60).count == 1
        assert system.purge_stale_drafts(uow, storage, ADMIN_VIEWER, older_than_days=60) == 1
    with backend.unit_of_work() as uow:
        assert imports.drafts(uow, owner_id=ANA_ID) == []
        assert len(imports.drafts(uow, owner_id=BETO_ID)) == 1
        assert audit.entries(uow)[0].details["drafts"] == 1


def test_usage_metrics_and_extraction_stats(uow, storage):
    purchase_service.create(uow, VALUES, [], owner_id=ANA_ID)
    upload(uow, storage)
    metrics = system.usage_metrics(uow, ADMIN_VIEWER)
    assert metrics.purchases == 1 and metrics.pending_drafts == 1
    assert metrics.users_by_role == {ADMIN: 1, CUSTOMER: 2}
    assert [n for _month, source, n in metrics.monthly_by_source if source == "manual"] == [1]
    stats = system.extraction_stats(uow, ADMIN_VIEWER)
    assert stats[0].method == "rules" and stats[0].total == 1


def test_service_checks_report_failures():
    def broken():
        raise RuntimeError("caído")

    result = system.check_services({"ok": lambda: "bien", "mal": broken})
    assert [(s.name, s.ok, s.detail) for s in result] == [("ok", True, "bien"), ("mal", False, "caído")]


def test_forecast_models_overview(uow):
    run = ForecastTrainingRun(scope=forecasting.SCOPE_USER, algorithm="ets", owner_id=ANA_ID)
    uow.forecast_runs.add(run)
    uow.commit()
    for version, mape, status in (("1", 30, forecasting.MODEL_ARCHIVED), ("2", 20, forecasting.MODEL_ACTIVE)):
        uow.forecast_models.add(
            ForecastModel(
                scope=forecasting.SCOPE_USER,
                algorithm="ets",
                version=version,
                owner_id=ANA_ID,
                run_id=run.id,
                metrics={"mape": mape},
                status=status,
            )
        )
    uow.commit()
    data = model_service.overview(uow, ADMIN_VIEWER)
    assert data.mean_accuracy == 80 and data.owner_label(data.active[0]) == "Ana"
    assert [m.version for m in data.history(data.active[0])] == ["1", "2"]
    with pytest.raises(PermissionDenied):
        model_service.overview(uow, ANA_VIEWER)


def test_deleting_user_removes_its_models(backend, storage, directory):
    with backend.unit_of_work() as uow:
        uow.forecast_models.add(
            ForecastModel(scope=forecasting.SCOPE_USER, algorithm="ets", version="1", owner_id=ANA_ID)
        )
        uow.forecast_models.add(ForecastModel(scope=forecasting.SCOPE_GLOBAL, algorithm="lgbm", version="1"))
        uow.commit()
        accounts.delete(uow, storage, directory, ADMIN_VIEWER, uow.users.get(ANA_ID))
    with backend.unit_of_work() as uow:
        assert [m.scope for m in uow.forecast_models.list()] == [forecasting.SCOPE_GLOBAL]
