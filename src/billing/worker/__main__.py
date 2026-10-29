"""`python -m billing.worker`: sincroniza periódicamente los buzones IMAP de
notificaciones bancarias de todos los usuarios y entrena los modelos de predicción.

Opciones: `--once` (una pasada y termina), `--interval N` (segundos; por defecto
BILLING_MAIL_SYNC_INTERVAL) y `--train` (entrena todos los modelos, incluido el general, y
termina). Toca /tmp/worker-alive tras cada pasada para el healthcheck de Docker.

Predicción: cada BILLING_FORECAST_INTERVAL revisa qué clientes tienen datos nuevos (solo
reentrena esos) y actualiza las predicciones; el modelo general se reentrena cada
BILLING_FORECAST_GLOBAL_INTERVAL.
"""

import argparse
import contextlib
import logging
import signal
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from billing import bootstrap, settings
from billing.application.bank_emails import sync
from billing.application.forecasting import training

HEARTBEAT = Path("/tmp/worker-alive")
log = logging.getLogger("billing.worker")
stop = threading.Event()


def run_once() -> list[sync.SyncReport]:
    reports = sync.sync_all(
        bootstrap.uow_factory(),
        gateway=bootstrap.mailbox_gateway(),
        cipher=bootstrap.secret_cipher(),
        parser=bootstrap.bank_parser(),
        storage=bootstrap.file_storage(),
        batch=settings.MAIL_SYNC_BATCH,
    )
    for report in reports:
        log.info("Buzón %s: %s", report.mailbox_id, report.summary())
    with contextlib.suppress(OSError):
        HEARTBEAT.touch()
    return reports


def train(*, force_global: bool) -> training.TrainingReport:
    with bootstrap.unit_of_work() as uow:
        last = training.last_global_training(uow)
    stale = last is None or datetime.now() - last >= timedelta(seconds=settings.FORECAST_GLOBAL_INTERVAL)
    report = training.train_all(
        bootstrap.uow_factory(),
        global_forecaster=bootstrap.global_forecaster(),
        series_forecaster=bootstrap.series_forecaster(),
        storage=bootstrap.file_storage(),
        retrain_global=force_global or stale,
    )
    log.info("Predicción: %s", report.summary())
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true", help="una sola pasada")
    parser.add_argument("--interval", type=int, default=settings.MAIL_SYNC_INTERVAL)
    parser.add_argument("--train", action="store_true", help="entrena los modelos de predicción y termina")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    bootstrap.init_database()  # idempotente: por si el worker arranca antes que la app
    if args.train:
        report = train(force_global=True)
        return 1 if report.errors or report.global_error else 0
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    log.info("Worker de buzones iniciado (cada %s s)", args.interval)
    next_training = 0.0  # la primera pasada también revisa los modelos
    while not stop.is_set():
        try:
            run_once()
        except Exception:  # un fallo (p. ej. base caída) no debe parar el worker
            log.exception("Fallo en la sincronización de buzones")
        if time.monotonic() >= next_training:
            next_training = time.monotonic() + settings.FORECAST_INTERVAL
            try:
                train(force_global=False)
            except Exception:  # entrenar no debe parar la sincronización de buzones
                log.exception("Fallo en el entrenamiento de los modelos de predicción")
        if args.once:
            break
        stop.wait(args.interval)
    log.info("Worker detenido")
    return 0


if __name__ == "__main__":
    sys.exit(main())
