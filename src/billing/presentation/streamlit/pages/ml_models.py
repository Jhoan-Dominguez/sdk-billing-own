"""Modelos de predicción (administradores): modelos entrenados, versiones, métricas y
entrenamientos. Solo cifras del modelo, nunca las predicciones de cada cliente."""

from datetime import datetime, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from billing import bootstrap
from billing.application.forecasting import models as model_service
from billing.domain import forecasting
from billing.presentation.streamlit.components.admin import require_manager, when
from billing.presentation.streamlit.components.layout import flash

viewer = require_manager()
head, action = st.columns([4, 1], vertical_alignment="bottom")
head.title("Modelos de predicción")
if action.button("Entrenar ahora", icon=":material/model_training:", width="stretch"):
    with st.spinner("Entrenando modelos y actualizando predicciones…"):
        report = model_service.train_now(
            bootstrap.uow_factory(),
            viewer,
            global_forecaster=bootstrap.global_forecaster(),
            series_forecaster=bootstrap.series_forecaster(),
            storage=bootstrap.file_storage(),
        )
    flash(report.summary().capitalize())
    st.rerun()
st.caption(
    "Predicción del gasto mensual por cliente: un modelo **general** que aprende de todos los clientes (series "
    "normalizadas, sin importes) y uno **por cliente y moneda** que lo personaliza. El worker reentrena cada hora a "
    "los clientes con datos nuevos y a diario el general. Las métricas salen del backtest."
)

with bootstrap.unit_of_work() as uow:
    data = model_service.overview(uow, viewer)


def pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f} %"


def metric(model, key: str) -> float | None:
    value = (model.metrics or {}).get(key)
    return float(value) if value is not None else None


# --- Resumen ------------------------------------------------------------------------

recent_failures = [
    r for r in data.runs if r.status == forecasting.RUN_FAILED and r.created_at >= datetime.now() - timedelta(days=30)
]
k1, k2, k3, k4 = st.columns(4)
k1.metric("Modelos activos", len(data.active), help="Uno general y uno por cada cliente con historia suficiente")
k2.metric("Acierto medio", pct(data.mean_accuracy), help="100 − MAPE de los modelos activos")
last = data.last_run
k3.metric(
    "Último entrenamiento",
    when(last.created_at) if last else "—",
    forecasting.RUN_STATUS_LABELS.get(last.status, last.status) if last else None,
    delta_color="inverse" if last and last.status == forecasting.RUN_FAILED else "normal",
)
k4.metric("Entrenamientos fallidos (30 días)", len(recent_failures))

if not data.models and not data.runs:
    st.info(
        "Todavía no hay modelos entrenados. Aparecerán cuando el worker ejecute el primer entrenamiento "
        "(o pulsa «Entrenar ahora»).",
        icon=":material/model_training:",
    )

models_tab, runs_tab, help_tab = st.tabs(
    [":material/model_training: Modelos", ":material/history: Entrenamientos", ":material/help: Métricas"]
)

# --- Modelos ------------------------------------------------------------------------

with models_tab:
    scope_col, status_col = st.columns(2)
    scope = scope_col.segmented_control(
        "Alcance",
        [None, *forecasting.SCOPE_LABELS],
        format_func=lambda s: "Todos" if s is None else forecasting.SCOPE_LABELS[s],
        default=None,
        key="ml-scope",
    )
    status = status_col.segmented_control(
        "Estado",
        [None, *forecasting.MODEL_STATUS_LABELS],
        format_func=lambda s: "Todos" if s is None else forecasting.MODEL_STATUS_LABELS[s],
        default=forecasting.MODEL_ACTIVE,
        key="ml-status",
    )
    shown = [m for m in data.models if (not scope or m.scope == scope) and (not status or m.status == status)]
    df = pd.DataFrame(
        [
            {
                "id": m.id,
                "Versión": m.version,
                "Alcance": forecasting.SCOPE_LABELS.get(m.scope, m.scope),
                "Cliente": data.owner_label(m),
                "Moneda": m.currency or "—",
                "Algoritmo": m.algorithm,
                "Estado": forecasting.MODEL_STATUS_LABELS.get(m.status, m.status),
                "Acierto": forecasting.accuracy_pct(m.metrics),
                "Error (MAPE)": forecasting.error_pct(m.metrics),
                "MAE": metric(m, forecasting.METRIC_MAE),
                "MASE": metric(m, forecasting.METRIC_MASE),
                "Cobertura P10–P90": metric(m, forecasting.METRIC_COVERAGE),
                "Muestras": m.n_samples,
                "Datos": f"{when(m.train_from, with_time=False)} – {when(m.train_to, with_time=False)}"
                if m.train_from
                else "—",
                "Entrenado": m.created_at,
            }
            for m in shown
        ],
        columns=[
            "id",
            "Versión",
            "Alcance",
            "Cliente",
            "Moneda",
            "Algoritmo",
            "Estado",
            "Acierto",
            "Error (MAPE)",
            "MAE",
            "MASE",
            "Cobertura P10–P90",
            "Muestras",
            "Datos",
            "Entrenado",
        ],
    )
    selection = st.dataframe(
        df,
        hide_index=True,
        column_order=[c for c in df.columns if c != "id"],
        column_config={
            "Acierto": st.column_config.ProgressColumn(format="%.1f %%", min_value=0, max_value=100, help="100 − MAPE"),
            "Error (MAPE)": st.column_config.NumberColumn(format="%.1f %%"),
            "MAE": st.column_config.NumberColumn(format="%.2f"),
            "MASE": st.column_config.NumberColumn(format="%.2f", help="< 1: mejor que repetir el mes anterior"),
            "Cobertura P10–P90": st.column_config.NumberColumn(format="%.0f %%", help="Lo ideal es cerca del 80 %"),
            "Entrenado": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
        },
        on_select="rerun",
        selection_mode="single-row",
        key=f"ml-models-{scope}-{status}",
    )
    if shown and not selection.selection.rows:
        st.caption("Selecciona un modelo para ver sus métricas, parámetros e historial de versiones.")

    if selection.selection.rows:
        model = next(m for m in shown if m.id == df.iloc[selection.selection.rows[0]]["id"])
        st.divider()
        st.subheader(
            f"{forecasting.SCOPE_LABELS.get(model.scope, model.scope)} · {data.owner_label(model)}"
            + (f" · {model.currency}" if model.currency else "")
        )
        st.caption(
            f"Versión **{model.version}** · {model.algorithm} · "
            f"{forecasting.MODEL_STATUS_LABELS.get(model.status, model.status)} · entrenado {when(model.created_at)}"
        )
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Acierto", pct(forecasting.accuracy_pct(model.metrics)))
        m2.metric("Error (MAPE)", pct(forecasting.error_pct(model.metrics)))
        mae = metric(model, forecasting.METRIC_MAE)
        m3.metric("MAE", "—" if mae is None else f"{mae:,.2f}")
        mase = metric(model, forecasting.METRIC_MASE)
        m4.metric("MASE", "—" if mase is None else f"{mase:.2f}")
        m5.metric("Cobertura P10–P90", pct(metric(model, forecasting.METRIC_COVERAGE)))
        beats = forecasting.beats_baseline(model.metrics)
        if beats is True:
            st.success("Supera a la referencia ingenua (repetir el mes anterior).", icon=":material/trending_up:")
        elif beats is False:
            st.warning("No supera a la referencia ingenua: conviene no activarlo.", icon=":material/trending_down:")

        history = data.history(model)
        if len(history) > 1:
            hist = pd.DataFrame(
                [
                    {
                        "Versión": m.version,
                        "Entrenado": m.created_at,
                        "Acierto": forecasting.accuracy_pct(m.metrics),
                        "Error (MAPE)": forecasting.error_pct(m.metrics),
                    }
                    for m in history
                ]
            )
            long = hist.melt(["Versión", "Entrenado"], ["Acierto", "Error (MAPE)"], "Métrica", "Porcentaje").dropna()
            chart = (
                alt.Chart(long)
                .mark_line(point=True)
                .encode(
                    x=alt.X("Entrenado:T", title="Entrenamiento"),
                    y=alt.Y("Porcentaje:Q", title="%", scale=alt.Scale(domain=[0, 100])),
                    color=alt.Color("Métrica:N", legend=alt.Legend(orient="bottom")),
                    tooltip=["Versión", "Métrica", alt.Tooltip("Porcentaje:Q", format=".1f")],
                )
                .properties(height=260, title="Evolución por versión")
            )
            st.altair_chart(chart, width="stretch")

        details, params = st.columns(2)
        with details:
            st.markdown("**Entrenamiento**")
            st.markdown(
                "\n".join(
                    f"- **{label}:** {value}"
                    for label, value in [
                        ("Muestras", f"{model.n_samples:,}" if model.n_samples else "—"),
                        ("Datos desde", when(model.train_from, with_time=False)),
                        ("Datos hasta", when(model.train_to, with_time=False)),
                        ("Ejecución", f"#{model.run_id}" if model.run_id else "—"),
                        ("Archivo", f"`{model.artifact_key}`" if model.artifact_key else "parámetros en la base"),
                    ]
                )
            )
            if model.features:
                st.markdown("**Variables de entrada**")
                st.markdown(" ".join(f"`{f}`" for f in model.features))
        with params:
            st.markdown("**Parámetros**")
            st.json(model.params or {}, expanded=False)
            extra = {k: v for k, v in (model.metrics or {}).items() if k not in forecasting.METRIC_LABELS}
            if extra:
                st.markdown("**Otras métricas**")
                st.json(extra, expanded=False)

# --- Entrenamientos -----------------------------------------------------------------

with runs_tab:
    runs = pd.DataFrame(
        [
            {
                "#": r.id,
                "Inicio": r.created_at,
                "Duración (s)": (r.finished_at - r.created_at).total_seconds() if r.finished_at else None,
                "Alcance": forecasting.SCOPE_LABELS.get(r.scope, r.scope),
                "Cliente": data.owner_label(r),
                "Moneda": data.run_currency(r) or "—",
                "Algoritmo": r.algorithm,
                "Estado": forecasting.RUN_STATUS_LABELS.get(r.status, r.status),
                "Muestras": r.n_samples,
                "Huella de datos": (r.data_fingerprint or "")[:12],
                "Error": r.error,
            }
            for r in data.runs
        ],
        columns=[
            "#",
            "Inicio",
            "Duración (s)",
            "Alcance",
            "Cliente",
            "Moneda",
            "Algoritmo",
            "Estado",
            "Muestras",
            "Huella de datos",
            "Error",
        ],
    )
    st.dataframe(
        runs,
        hide_index=True,
        column_config={
            "Inicio": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
            "Duración (s)": st.column_config.NumberColumn(format="%.1f"),
            "Huella de datos": st.column_config.TextColumn(help="Hash de los datos usados (reproducibilidad)"),
        },
    )
    if runs.empty:
        st.caption("Sin entrenamientos registrados.")

# --- Ayuda --------------------------------------------------------------------------

with help_tab:
    st.markdown(
        """
- **Acierto** = 100 − MAPE. Es la medida más fácil de leer, pero se infla con meses de gasto alto.
- **Error (MAPE)**: error porcentual medio de la predicción frente al gasto real del mes.
- **MAE**: error medio en la unidad del objetivo (moneda del cliente; proporción en el modelo general).
- **MASE**: error relativo a repetir el mes anterior. Menor que 1 = el modelo aporta; un modelo nuevo solo
  se activa si mejora a la referencia.
- **Cobertura P10–P90**: cuántas veces el gasto real cayó dentro del rango predicho (lo ideal, ~80 %).
- Las métricas salen de un **backtest con origen móvil**: se entrena hasta un mes y se mide el siguiente.
"""
    )
