"""Modelo de datos (administradores): diagrama entidad-relación, detalle de cada tabla y
migraciones. Solo consulta: el esquema se cambia con migraciones de Alembic en el código."""

from html import escape

import pandas as pd
import streamlit as st

from billing import bootstrap
from billing.domain.schema import SchemaInfo, TableInfo
from billing.presentation.streamlit.components.admin import require_manager

require_manager()
st.title("Modelo de datos")

schema = bootstrap.describe_schema()
if schema is None:
    st.info(
        "El motor de persistencia actual no tiene esquema (p. ej. `BILLING_PERSISTENCE=memory`).",
        icon=":material/info:",
    )
    st.stop()


def er_diagram(schema: SchemaInfo) -> str:
    """Diagrama en DOT: cada tabla con sus columnas; las flechas van de la clave foránea a la tabla."""
    lines = [
        "digraph {",
        "rankdir=LR; bgcolor=transparent; nodesep=0.4; ranksep=0.9;",
        'node [shape=plain fontname="Helvetica" fontsize=10];',
        'edge [fontname="Helvetica" fontsize=8 color="#7a7f87" fontcolor="#7a7f87" arrowsize=0.7];',
    ]
    for table in schema.tables:
        fk_columns = {c for fk in table.foreign_keys for c in fk.columns}
        rows = [
            f'<tr><td bgcolor="#2f6fed" colspan="2"><font color="white"><b>{escape(table.name)}</b></font></td></tr>'
        ]
        for column in table.columns:
            mark = "PK" if column.primary_key else ("FK" if column.name in fk_columns else "")
            name = f"<b>{escape(column.name)}</b>" if column.primary_key else escape(column.name)
            if not column.nullable and not column.primary_key:
                name += " *"
            rows.append(
                f'<tr><td align="left" port="{escape(column.name)}">{mark and f"<i>{mark}</i> "}{name}</td>'
                f'<td align="left"><font color="#7a7f87">{escape(column.type.lower())}</font></td></tr>'
            )
        label = '<table border="0" cellborder="1" cellspacing="0" cellpadding="4">' + "".join(rows) + "</table>"
        lines.append(f'"{table.name}" [label=<{label}>];')
    for table in schema.tables:
        for fk in table.foreign_keys:
            label = fk.on_delete.lower() if fk.on_delete else ""
            lines.append(
                f'"{table.name}":"{fk.columns[0]}" -> "{fk.ref_table}":"{fk.ref_columns[0]}" [label="{label}"];'
            )
    lines.append("}")
    return "\n".join(lines)


k1, k2, k3, k4 = st.columns(4)
k1.metric("Motor", schema.engine)
k2.metric("Tablas", len(schema.tables))
k3.metric("Filas", f"{sum(t.row_count or 0 for t in schema.tables):,}")
k4.metric(
    "Migración",
    schema.current_revision or "—",
    f"{len(schema.pending_migrations)} pendiente(s)" if schema.pending_migrations else "al día",
    delta_color="inverse" if schema.pending_migrations else "off",
)

diagram_tab, tables_tab, migrations_tab = st.tabs(
    [":material/schema: Diagrama", ":material/table: Tablas", ":material/history: Migraciones"]
)

with diagram_tab:
    st.graphviz_chart(er_diagram(schema), width="stretch")
    st.caption("**PK** clave primaria · **FK** clave foránea · `*` obligatoria · en las flechas, qué pasa al borrar.")

with tables_tab:
    tables = {t.name: t for t in schema.tables}
    overview = pd.DataFrame(
        [
            {
                "Tabla": t.name,
                "Columnas": len(t.columns),
                "Relaciones": len(t.foreign_keys),
                "Índices": len(t.indexes),
                "Filas": t.row_count,
            }
            for t in schema.tables
        ]
    )
    st.dataframe(overview, hide_index=True)
    name = st.selectbox("Detalle de la tabla", list(tables))
    table: TableInfo = tables[name]
    referenced_by = [(t.name, fk) for t in schema.tables for fk in t.foreign_keys if fk.ref_table == name]

    st.markdown(f"**Columnas de `{name}`**")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Columna": c.name,
                    "Tipo": c.type,
                    "Clave primaria": c.primary_key,
                    "Obligatoria": not c.nullable,
                    "Valor por defecto": c.default or "",
                }
                for c in table.columns
            ]
        ),
        hide_index=True,
    )
    left, right = st.columns(2)
    with left:
        st.markdown("**Relaciones**")
        relations = [
            f"- `{', '.join(fk.columns)}` → `{fk.ref_table}.{', '.join(fk.ref_columns)}`"
            + (f" (al borrar: {fk.on_delete})" if fk.on_delete else "")
            for fk in table.foreign_keys
        ] + [
            f"- `{other}.{', '.join(fk.columns)}` apunta aquí"
            + (f" (al borrar: {fk.on_delete})" if fk.on_delete else "")
            for other, fk in referenced_by
        ]
        st.markdown("\n".join(relations) or "Sin relaciones.")
    with right:
        st.markdown("**Índices**")
        st.markdown(
            "\n".join(
                f"- `{i.name}` ({', '.join(i.columns)})" + (" · único" if i.unique else "") for i in table.indexes
            )
            or "Sin índices."
        )

with migrations_tab:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Revisión": m.revision,
                    "Descripción": m.description.splitlines()[0] if m.description else "",
                    "Aplicada": m.applied,
                }
                for m in schema.migrations
            ]
        ),
        hide_index=True,
    )
    st.markdown(
        """
**Para modificar el modelo de datos**
1. Cambia la tabla en `infrastructure/persistence/sqlalchemy/tables.py` (y la entidad en `domain/models.py`).
2. Escribe la migración: `.venv/bin/alembic revision -m "..."` (a mano, con `batch_alter_table` para SQLite).
3. `make migrate` y comprueba que `.venv/bin/alembic check` no reporta diferencias.
4. Si el cambio afecta a los datos de un usuario, actualiza la exportación (`application/admin/backup.py`).
"""
    )
