"""`python -m billing.worker`: sincroniza periódicamente los buzones IMAP de
notificaciones bancarias de todos los usuarios.

Opciones: `--once` (una pasada y termina) e `--interval N` (segundos; por defecto
BILLING_MAIL_SYNC_INTERVAL). Toca /tmp/worker-alive tras cada pasada para el
healthcheck de Docker.
"""

import argparse
import contextlib
import logging
import signal
import sys
import threading
from pathlib import Path

from billing import bootstrap, settings
from billing.application.bank_emails import sync

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true", help="una sola pasada")
    parser.add_argument("--interval", type=int, default=settings.MAIL_SYNC_INTERVAL)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    bootstrap.init_database()  # idempotente: por si el worker arranca antes que la app
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    log.info("Worker de buzones iniciado (cada %s s)", args.interval)
    while not stop.is_set():
        try:
            run_once()
        except Exception:  # un fallo (p. ej. base caída) no debe parar el worker
            log.exception("Fallo en la sincronización de buzones")
        if args.once:
            break
        stop.wait(args.interval)
    log.info("Worker detenido")
    return 0


if __name__ == "__main__":
    sys.exit(main())
