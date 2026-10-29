# Modelos de predicción del gasto

Referencia completa de cómo la app predice el gasto mensual de cada cliente: qué datos usa,
qué modelos entrena, cómo se evalúan, dónde se guarda cada cosa, quién los entrena y quién
consume sus resultados.

- **Cliente**: en el **Resumen** del mes en curso ve el cierre estimado del mes, lo previsto
  para el mes siguiente con un rango probable y un aviso si va por encima de lo habitual.
- **Administrador**: en **Modelos de predicción** ve los modelos, sus versiones y métricas, los
  entrenamientos y puede pulsar «Entrenar ahora». Nunca ve las predicciones de un cliente.

## Vista general

```
purchases ──▶ series mensuales por (cliente, moneda) ──┬──▶ modelo general (LightGBM) ──┐
              (application/forecasting/series.py)      │    todas las series            │
                                                       └──▶ modelo de cada cliente (ETS)┤
                                                            su propia serie             │
                                                                                        ▼
                     spend_forecasts ◀── combinación según la historia del cliente (blend)
                            │
             ┌──────────────┴───────────────┐
             ▼                              ▼
   Resumen del cliente (outlook)    Modelos de predicción (admin: métricas, no predicciones)
```

| Capa | Archivos |
|---|---|
| Dominio | `domain/forecasting.py` (constantes, `MonthlySeries`, `Quantiles`, `user_weight`, `blend`, `backtest_metrics`, `history_scale`), `domain/ports/forecasting.py` (`GlobalForecaster`, `SeriesForecaster`, `TrainedModel`, `ForecastingError`), entidades `ForecastTrainingRun`, `ForecastModel`, `SpendForecast` en `domain/models.py` |
| Aplicación | `application/forecasting/series.py`, `training.py`, `outlook.py`, `models.py` |
| Infraestructura | `infrastructure/ml/features.py`, `lightgbm_model.py`, `ets.py`, `baseline.py`, `registry.py` |
| Composición | `bootstrap.global_forecaster()`, `bootstrap.series_forecaster()` |
| Entradas | `worker/__main__.py` (bucle y `--train`), página `ml_models.py` («Entrenar ahora»), componente `forecast.py` (Resumen) |

## 1. Datos de entrenamiento

**No se copian a ninguna tabla.** En cada entrenamiento, `build_series` los deriva de
`purchases` con `purchases.monthly_totals(owner_id=None)` (total por cliente, moneda y mes).
Así, editar o borrar una compra, o eliminar una cuenta, se refleja en el siguiente
entrenamiento sin sincronizar nada.

Una **serie** (`MonthlySeries`) es el gasto mensual de un cliente en **una moneda**:

- Las monedas nunca se mezclan: un cliente con compras en COP y EUR tiene dos series.
- Va del primer mes con compras al **último mes completo** (el mes en curso no entra: está a
  medias).
- Los meses sin compras valen 0.

```
cliente A, COP: 2025-07 … 2026-09  →  (1.2M, 0.9M, 1.4M, 0, 1.1M, …)
cliente A, EUR: 2026-04 … 2026-09  →  (0, 850, 0, 0, 0, 0)
```

La **huella** (`fingerprint`) es un SHA-256 de la serie (meses y valores redondeados). Si no
cambió desde el último entrenamiento de ese cliente, su modelo no se reentrena.

## 2. Modelo general (LightGBM)

Un solo modelo para todos los clientes, en `infrastructure/ml/lightgbm_model.py`.

**Normalización.** Cada muestra es un mes `t` de una serie. Todo se divide por la **escala**
del cliente: su gasto medio en los 12 meses anteriores a `t` (`history_scale`). El objetivo es
`gasto(t) / escala`. Así el modelo aprende patrones (estacionalidad, inercia, rachas) que valen
para cualquier moneda y nivel de gasto, y sirve también para clientes nuevos.

**Variables** (`features.py`; los meses que faltan al principio quedan como `NaN`, que LightGBM maneja):

| Variable | Definición (sobre la serie normalizada) |
|---|---|
| `lag_1`, `lag_2`, `lag_3`, `lag_6`, `lag_12` | Gasto de hace 1, 2, 3, 6 y 12 meses |
| `mean_3`, `mean_6` | Media de los últimos 3 y 6 meses |
| `std_6` | Desviación estándar de los últimos 6 meses |
| `trend` | `lag_1 − lag_3` |
| `month` | Mes del año que se predice (1–12) |
| `history` | Meses de historia disponibles |

Solo se usan como muestra los meses con al menos 3 meses previos y escala mayor que 0.

**Entrenamiento.** Tres modelos de regresión por cuantiles (objetivo `quantile`, α = 0,1 /
0,5 / 0,9): dan P10, P50 y P90, es decir, un rango del 80 %.

| Hiperparámetro | Valor |
|---|---|
| Rondas | `min(300, max(50, 2 × muestras))` |
| `learning_rate` | 0,05 |
| `num_leaves` | 15 |
| `min_data_in_leaf` | `max(3, min(20, muestras / 10))` |
| `feature_fraction` | 0,9 |
| `seed` / `deterministic` | 7 / sí (mismo resultado con los mismos datos) |
| Mínimo de muestras | 12 (si no, `ForecastingError` y queda el modelo anterior) |

**Predicción.** Para varios meses se encadena: la P50 de un mes entra como historia del
siguiente. Los resultados se vuelven a multiplicar por la escala del cliente y se ordenan
(P10 ≤ P50 ≤ P90, nunca negativos). Si el cliente no gastó nada en el último año, se predice 0.

**Artefacto.** JSON en el `FileStorage`, en `models/global/<versión>.json`. Los tres modelos
van en el formato de texto de LightGBM; **no se usa pickle**, así que cargarlo no ejecuta código:

```json
{"format": "billing-lightgbm", "version": 1, "features": ["lag_1", "…"],
 "boosters": {"p10": "tree\nversion=v4…", "p50": "…", "p90": "…"}}
```

Al cargarlo se comprueba que `features` coincida con el código actual; si se cambian las
variables, el modelo guardado se rechaza y hay que reentrenar. Los modelos cargados se
cachean por el hash del artefacto.

Si LightGBM no está instalado (falta el extra `ml`) o `BILLING_FORECAST_ALGORITHM=baseline`,
`bootstrap` usa la referencia ingenua como modelo general.

## 3. Modelo de cada cliente (ETS con tendencia amortiguada)

Uno por cliente y moneda, en `infrastructure/ml/ets.py`, solo si la serie tiene al menos 3
meses (`MIN_USER_MONTHS`).

**Ecuaciones** (suavizado exponencial A,Ad,N), con nivel `ℓ`, tendencia `b` y amortiguación `φ`:

```
previsión a un paso:  ŷ(t) = ℓ(t−1) + φ·b(t−1)
nivel:                ℓ(t) = α·y(t) + (1 − α)·ŷ(t)
tendencia:            b(t) = β·(ℓ(t) − ℓ(t−1)) + (1 − β)·φ·b(t−1)
a h meses:            ŷ(t+h) = ℓ(t) + (φ + φ² + … + φʰ)·b(t)
```

- **Inicio**: `ℓ = y(0)`; `b` = pendiente media de los primeros meses (hasta 3).
- **Parámetros**: rejilla α ∈ {0,1; 0,2; 0,3; 0,5; 0,7}, β ∈ {0; 0,05; 0,1; 0,2},
  φ ∈ {0,8; 0,9; 0,98}; se elige la combinación con menor suma de errores a un paso.
- **Rango**: `σ` = raíz del error cuadrático medio a un paso; P10/P90 = previsión ∓ 1,2816·σ·√h.
- **Estacionalidad** (con 24 meses o más): factor multiplicativo por mes del año = media de ese
  mes / media general, encogido a la mitad hacia 1 para no sobreajustar. Se quita antes de
  suavizar y se vuelve a aplicar al predecir.

**Parámetros guardados** en `ml_models.params` (JSON), con el estado al final de la serie para
poder predecir sin volver a leer las compras:

```json
{"alpha": 0.3, "beta": 0.05, "phi": 0.9, "level": 812.4, "trend": 6.1, "sigma": 140.2,
 "seasonal": {"01": 0.94, "12": 1.12, "…": 1.0}, "last_month": "2026-09"}
```

## 4. Referencia ingenua

`baseline.py`: la media de los últimos 3 meses, con un rango según la desviación de los
últimos 6. Sirve de respaldo (sin LightGBM) y de vara de medir: un modelo útil debe superarla
(MASE < 1).

## 5. Combinación

Para cada mes previsto, `blend` mezcla ambos modelos por cuantil:
`final = w · cliente + (1 − w) · general`, con un peso `w` que crece con la historia
(`user_weight`):

| Meses de historia | Peso del modelo del cliente |
|---|---|
| 0–2 | 0 (solo el general) |
| 3 | 0,08 |
| 6 | 0,32 |
| 9 | 0,56 |
| 12 o más | 0,8 (máximo) |

Si falta uno de los dos modelos (p. ej. el general falló), se usa el otro.

## 6. Evaluación

**Backtest con origen móvil** (`training.backtest_global`, `backtest_series`): para cada uno de
los últimos 6 meses (`BACKTEST_MONTHS`) se entrena solo con los meses anteriores y se predice
ese mes.

```
datos:     ███████████████░░░░░░
origen 1:  ██████████  →  ▲ predice el mes 11
origen 2:  ███████████  →  ▲ predice el mes 12
…
```

El modelo general se mide en la escala de cada cliente (gasto / su media), así se pueden
mezclar monedas. El de un cliente se mide en su moneda.

| Métrica (`metrics`) | Fórmula | Cómo leerla |
|---|---|---|
| `mape` | media de \|real − P50\| / real × 100 (meses con gasto) | Error porcentual; **acierto = 100 − MAPE** |
| `mae` | media de \|real − P50\| | Error en la unidad del objetivo |
| `mase` | MAE / MAE de «repetir el mes anterior» | < 1: el modelo aporta; ≥ 1: no supera a la referencia |
| `coverage` | % de meses con P10 ≤ real ≤ P90 | Ideal ≈ 80 %; mucho menos = rango optimista |
| `evaluations` | meses evaluados | Pocas evaluaciones = métricas poco fiables |

Además del backtest, cada predicción guarda el gasto real cuando su mes se cierra
(`spend_forecasts.actual`). El **acierto real** que ve el cliente sale de ahí.

## 7. Almacenamiento

| Qué | Dónde | Notas |
|---|---|---|
| Datos de entrenamiento | `purchases` (no se copian) | Huella en `ml_training_runs.data_fingerprint` |
| Cada entrenamiento | `ml_training_runs` | Alcance, cliente, algoritmo, estado (`running`/`succeeded`/`failed`), error, muestras, inicio y fin |
| Modelos | `ml_models` | Alcance, cliente y moneda (NULL en el general), algoritmo, versión `AAAAMMDD.<run>`, métricas, variables, rango de datos, estado |
| Modelo general | `FileStorage`: `models/global/<versión>.json` | `ml_models.artifact_key` |
| Modelo de un cliente | `ml_models.params` (JSON) | Unos pocos números |
| Predicciones | `spend_forecasts` | Una por cliente, moneda y mes: P10/P50/P90, peso del cliente, modelos usados, `actual` |

Columnas completas en [modelo-de-datos.md](modelo-de-datos.md) (migraciones `0007` y `0008`).

**Ciclo de vida.**

- Solo hay un modelo `active` por alcance (y por cliente y moneda). Al activar uno nuevo, el
  anterior pasa a `archived`, con su fila y sus métricas, para comparar versiones.
- Las versiones archivadas del general conservan su archivo hasta 10. Las más antiguas lo
  pierden; la fila queda.
- Una predicción se reescribe en cada entrenamiento **mientras su mes no haya empezado**. Desde
  que empieza queda fija, y al cerrarse guarda el real. Así se compara con lo que se predijo
  antes de empezar el mes.
- Las fechas de ejecuciones y modelos las pone la app, no `now()` de la base (que en Postgres
  va en UTC), para que duraciones y plazos usen el mismo reloj.

## 8. Entrenamiento

`training.train_all` hace una pasada completa:

1. Reentrena el **general** si se pide (a diario o «Entrenar ahora») o si no hay uno activo.
   El intento queda en `ml_training_runs`; si falla, sigue activo el anterior.
2. Por cada serie con 3 meses o más, reentrena el modelo del cliente **solo si su huella
   cambió** (o cambió el algoritmo). Calcula sus métricas con el backtest.
3. Escribe las predicciones de los próximos `HORIZON` (4) meses desde el último mes completo
   (el primero es el mes en curso) y el gasto real de los meses ya cerrados.

Cada serie se procesa en su propia transacción: si una falla, se registra y se sigue con las demás.

| Quién | Cuándo | Modelo general |
|---|---|---|
| Worker (`python -m billing.worker`) | Primera pasada y cada `BILLING_FORECAST_INTERVAL` (3600 s) | Si el activo tiene más de `BILLING_FORECAST_GLOBAL_INTERVAL` (86400 s) |
| «Entrenar ahora» (Modelos de predicción) | A demanda; queda en la auditoría | Siempre |
| `make train` (`python -m billing.worker --train`) | A demanda | Siempre |

Con los datos de desarrollo (4 clientes, 12 meses) una pasada completa tarda alrededor de un segundo.

## 9. Consumo

**Cliente** (`application/forecasting/outlook.py`, componente `components/forecast.py`). Solo
lee sus propias filas de `spend_forecasts`; no entrena nada mientras navega.

- **Cierre estimado del mes**:
  - `p` = fracción del gasto mensual que el cliente suele llevar a estas alturas del mes
    (curva de sus últimos 6 meses; sin historia, la fracción de días transcurridos).
  - Ritmo = gastado hasta hoy / `p` (si `p` ≥ 0,05).
  - Estimado = `max(gastado, p · ritmo + (1 − p) · P50 del mes)`. Al principio del mes pesa la
    predicción y al final, el ritmo real.
  - El rango se calcula igual con P10 y P90; sin predicción, ritmo × 0,8 y × 1,2.
- **Previsto para el mes siguiente**: P50 con el rango P10–P90.
- **Aviso** si el cierre estimado supera el P90 previsto para el mes.
- **Acierto real**: 100 − error medio de sus meses ya cerrados.
- Gráfico: barras de gasto real de los últimos 6 meses y del mes en curso, más rombos con la
  previsión y su rango.

**Administrador** (`application/forecasting/models.py`, página `ml_models.py`): modelos activos,
acierto medio, último entrenamiento, fallos, tabla de modelos con filtros, detalle con
parámetros, variables y evolución por versión, e historial de entrenamientos.

## 10. Operación

| Tarea | Cómo |
|---|---|
| Entrenar ya | «Entrenar ahora» o `make train` |
| Ver por qué falló | Modelos de predicción → Entrenamientos (columna Error); `make logs SERVICE=worker` |
| Cambiar el algoritmo general | `BILLING_FORECAST_ALGORITHM=baseline` (o `lightgbm`) y reiniciar el worker |
| Cambiar la frecuencia | `BILLING_FORECAST_INTERVAL`, `BILLING_FORECAST_GLOBAL_INTERVAL` |
| Volver a una versión anterior del general | No hay botón. Mientras conserve su archivo: poner `status='archived'` en el activo y `status='active'` en el elegido (`ml_models`). El siguiente reentreno diario lo reemplaza |
| Dependencias | Extra `ml` (`lightgbm`, que trae scipy). La imagen instala `.[llm,ml]` y `libgomp1` (OpenMP) |

## 11. Extender

- **Otro algoritmo general**: una clase con `algorithm`, `fit(series) -> TrainedModel` y
  `predict(artifact, series, horizon)`, registrada en `infrastructure/ml/registry.py` (`GLOBAL`).
  Para el de cliente: `fit(series) -> dict` y `predict(params, horizon)` en `SERIES`.
- **Otras variables**: cambiar `FEATURES` y `row()` en `features.py`. Los modelos guardados
  dejan de ser compatibles (se rechazan al cargar) y el siguiente entrenamiento los reemplaza.
- **Por categoría**: las series serían por (cliente, moneda, categoría). Habría que añadir la
  categoría a `MonthlySeries`, a `ml_models` y a `spend_forecasts`.

## 12. Privacidad y borrado

- El administrador ve métricas y entrenamientos, nunca las predicciones de un cliente.
- El modelo general aprende de las series **normalizadas** de todos, sin datos personales.
  Conviene mencionarlo en los términos de uso.
- Al eliminar una cuenta se borran sus modelos y predicciones (cascada) y sus archivos de
  modelo (`users.delete_account`). Sus datos salen del modelo general en el siguiente
  reentreno diario.
- La exportación de un usuario no incluye modelos ni predicciones. Tras restaurarlo no tiene
  modelo activo, y el worker se lo entrena en su siguiente pasada.

## 13. Limitaciones

- Con poca historia (o datos muy irregulares) los rangos son anchos y el acierto, moderado. El
  modelo general necesita al menos 12 muestras entre todos los clientes.
- Una compra muy grande y puntual (un viaje) infla el mes y la escala del cliente durante un año.
- No se predice por categoría ni por comercio, solo el total por moneda.
- No hay alertas por correo: el aviso se ve solo en el Resumen.
