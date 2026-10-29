"""Estado del sistema (administradores): servicios, buzones y worker, agentes IA, métricas
de uso (sin importes) y retención de datos."""

import altair as alt
import pandas as pd
import streamlit as st

from billing import bootstrap, settings
from billing.application.admin import system
from billing.domain.auth import ROLE_LABELS
from billing.domain.catalog import SOURCE_LABELS
from billing.presentation.streamlit.components.admin import ACTION_ERRORS, human_bytes, require_manager, when
from billing.presentation.streamlit.components.formatting import month_label
from billing.presentation.streamlit.components.layout import flash

viewer = require_manager()
st.title("Estado del sistema")

services_tab, mail_tab, agents_tab, usage_tab, retention_tab = st.tabs(
    [
        ":material/dns: Servicios",
        ":material/forward_to_inbox: Buzones y worker",
        ":material/smart_toy: Agentes IA",
        ":material/insights: Uso",
        ":material/auto_delete: Retención",
    ]
)

# --- Servicios ------------------------------------------------------------------------

with services_tab:
    if st.button("Comprobar de nuevo", icon=":material/refresh:"):
        st.rerun()
    with st.spinner("Comprobando servicios…"):
        statuses = system.check_services(bootstrap.service_checks())
    for status in statuses:
        with st.container(border=True):
            icon = ":material/check_circle:" if status.ok else ":material/error:"
            color = "green" if status.ok else "red"
            st.markdown(f":{color}[{icon}] **{status.name}** · {status.detail}")
    provider, model, _ = bootstrap.agent_choice("invoice")
    st.caption(
        f"Persistencia `{settings.PERSISTENCE_BACKEND}` · almacenamiento `{settings.STORAGE_BACKEND}` · correo "
        f"`{settings.MAILER_BACKEND}` · lector de facturas `{provider}`" + (f" (`{model}`)" if model else "")
    )

# --- Buzones y worker -------------------------------------------------------------------

with mail_tab, bootstrap.unit_of_work() as uow:
    health = system.mailbox_health(uow, viewer, interval_seconds=settings.MAIL_SYNC_INTERVAL)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Buzones", health.total)
    k2.metric("Activos", health.enabled)
    k3.metric("Con error", len(health.failing))
    k4.metric("Última sincronización", when(health.last_sync))
    if health.worker_ok is None:
        st.info("No hay buzones activos: no se puede saber si el worker está sincronizando.", icon=":material/info:")
    elif health.worker_ok:
        st.success(
            f"El worker sincroniza con normalidad (cada {settings.MAIL_SYNC_INTERVAL} s).", icon=":material/sync:"
        )
    else:
        st.error(
            "Ningún buzón se sincronizó en los últimos tres intervalos: revisa el servicio `worker`.",
            icon=":material/sync_problem:",
        )

    def mailbox_rows(items):
        return pd.DataFrame(
            [
                {
                    "Usuario": user.display_name if user else m.owner_id,
                    "Servidor": f"{m.host}:{m.port}",
                    "Carpeta": m.folder,
                    "Última sincronización": m.last_sync_at,
                    "Importados": m.imported_count,
                    "Error": m.last_error,
                }
                for user, m in items
            ]
        )

    if health.failing:
        st.subheader("Buzones con error")
        st.dataframe(
            mailbox_rows(health.failing),
            hide_index=True,
            column_config={"Última sincronización": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm")},
        )
    stale_only = [item for item in health.stale if item not in health.failing]
    if stale_only:
        st.subheader("Buzones sin sincronizar recientemente")
        st.dataframe(
            mailbox_rows(stale_only),
            hide_index=True,
            column_config={"Última sincronización": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm")},
        )

# --- Agentes IA -----------------------------------------------------------------------

DOCUMENT_LABELS = {"invoice": "Factura", "bank_notification": "Notificación bancaria"}
METHOD_LABELS = {"llm": "Agente IA", "rules": "Reglas"}

with agents_tab:
    days = st.segmented_control(
        "Periodo", [7, 30, 90], format_func=lambda d: f"{d} días", default=30, key="agents-days", required=True
    )
    with bootstrap.unit_of_work() as uow:
        stats = system.extraction_stats(uow, viewer, days=days)
    if not stats:
        st.info(f"No hubo extracciones en los últimos {days} días.", icon=":material/info:")
    else:
        total = sum(s.total for s in stats)
        errors = sum(s.errors for s in stats)
        rules = sum(s.total for s in stats if s.method == "rules")
        k1, k2, k3 = st.columns(3)
        k1.metric("Documentos procesados", f"{total:,}")
        k2.metric("Con error de extracción", f"{errors:,}", f"{100 * errors / total:.1f} %", delta_color="inverse")
        k3.metric("Resueltos solo con reglas", f"{rules:,}", help="Sin agente IA o porque el agente falló")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Documento": DOCUMENT_LABELS.get(s.document_type, s.document_type),
                        "Método": METHOD_LABELS.get(s.method, s.method),
                        "Proveedor": s.provider or "—",
                        "Modelo": s.model or "—",
                        "Documentos": s.total,
                        "Errores": s.errors,
                        "% error": s.error_pct,
                        "Tiempo medio (s)": s.avg_seconds,
                    }
                    for s in stats
                ]
            ),
            hide_index=True,
            column_config={
                "% error": st.column_config.NumberColumn(format="%.1f %%"),
                "Tiempo medio (s)": st.column_config.NumberColumn(format="%.1f"),
            },
        )
        st.caption("Un error significa que el documento quedó para completar a mano (nunca se pierde la subida).")

# --- Uso -------------------------------------------------------------------------------

with usage_tab, bootstrap.unit_of_work() as uow:
    metrics = system.usage_metrics(uow, viewer, months=6)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric(
        "Usuarios",
        sum(metrics.users_by_role.values()),
        help=" · ".join(f"{ROLE_LABELS.get(r, r)}: {n}" for r, n in metrics.users_by_role.items()),
    )
    k2.metric("Activos (30 días)", metrics.active_30d)
    k3.metric("Nuevos (30 días)", metrics.new_30d)
    k4.metric("Bloqueados", metrics.blocked)
    k5, k6, k7, _ = st.columns(4)
    k5.metric("Compras registradas", f"{metrics.purchases:,}")
    k6.metric("Borradores pendientes", f"{metrics.pending_drafts:,}")
    k7.metric("Archivos almacenados", f"{metrics.files:,}", human_bytes(metrics.bytes), delta_color="off")
    if metrics.monthly_by_source:
        df = pd.DataFrame(metrics.monthly_by_source, columns=["Mes", "Origen", "Compras"])
        df["Origen"] = df["Origen"].map(lambda s: SOURCE_LABELS.get(s, s))
        df["Etiqueta"] = df["Mes"].map(month_label)
        chart = (
            alt.Chart(df)
            .mark_bar()
            .encode(
                x=alt.X("Etiqueta:N", sort=list(dict.fromkeys(df.sort_values("Mes")["Etiqueta"])), title=None),
                y=alt.Y("sum(Compras):Q", title="Compras registradas"),
                color=alt.Color("Origen:N", legend=alt.Legend(orient="bottom")),
                tooltip=["Etiqueta", "Origen", "Compras"],
            )
            .properties(height=300, title="Compras registradas por mes y origen (cantidad, sin importes)")
        )
        st.altair_chart(chart, width="stretch")

# --- Retención -----------------------------------------------------------------------

with retention_tab:
    st.subheader("Borradores sin revisar")
    older = st.number_input("Más antiguos que (días)", min_value=7, max_value=3650, value=60, step=1)
    with bootstrap.unit_of_work() as uow:
        stale = system.stale_drafts(uow, viewer, older_than_days=int(older))
    st.write(f"**{stale.count:,}** borradores de **{stale.users}** usuario(s) ocupan **{human_bytes(stale.bytes)}**.")
    with st.popover("Purgar borradores", icon=":material/delete_sweep:", disabled=not stale.count):
        st.write("Se descartan esos borradores y sus archivos. Sus dueños no podrán recuperarlos.")
        if st.button("Sí, purgar", key="confirm-delete-drafts"):
            try:
                with bootstrap.unit_of_work() as uow:
                    purged = system.purge_stale_drafts(
                        uow, bootstrap.file_storage(), viewer, older_than_days=int(older)
                    )
            except ACTION_ERRORS as e:
                st.error(str(e), icon=":material/error:")
            else:
                flash(f"{purged} borradores purgados")
                st.rerun()

    st.divider()
    st.subheader("Cuentas inactivas")
    months = st.number_input("Sin iniciar sesión en (meses)", min_value=1, max_value=60, value=6, step=1)
    with bootstrap.unit_of_work() as uow:
        inactive = system.inactive_users(uow, viewer, months=int(months))
    if not inactive:
        st.caption("No hay cuentas inactivas en ese periodo.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Nombre": u.display_name,
                        "Correo": u.email,
                        "Rol": ROLE_LABELS.get(u.role, u.role),
                        "Último acceso": u.last_login_at,
                        "Bloqueada": u.is_disabled,
                    }
                    for u in inactive
                ]
            ),
            hide_index=True,
            column_config={"Último acceso": st.column_config.DatetimeColumn(format="DD/MM/YYYY")},
        )
        st.caption("Para exportar, bloquear o eliminar una de estas cuentas usa la página **Usuarios**.")
