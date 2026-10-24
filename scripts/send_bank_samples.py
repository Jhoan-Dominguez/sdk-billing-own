"""Envía notificaciones bancarias de PRUEBA a la bandeja de GreenMail (sin Internet).

Simula las alertas de Bancolombia, Davivienda, BBVA, Banco de Bogotá y Nequi (esta
última sin plantilla de reglas: la lee el agente LLM si hay uno configurado) más un
correo publicitario que debe ignorarse. Las fechas son de los últimos días.

    .venv/bin/python scripts/send_bank_samples.py                       # a cliente@billing.example.com
    .venv/bin/python scripts/send_bank_samples.py --to maria.lopez@billing.example.com
    .venv/bin/python scripts/send_bank_samples.py --connect             # y conecta el buzón en la app
    docker compose exec app python scripts/send_bank_samples.py --connect   (make bank-samples)

--connect crea (si no existe) la conexión IMAP del usuario dueño de ese correo hacia
GreenMail, para que el worker o "Sincronizar ahora" lean los correos enviados.
"""

import argparse
import os
import smtplib
import sys
import uuid
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid

from billing import bootstrap
from billing.application.bank_emails import mailboxes as mailbox_service

IN_DOCKER = os.environ.get("POSTGRES_HOST") == "db"
DEFAULT_HOST = "greenmail" if IN_DOCKER else "localhost"
SMTP_PORT = 3025
IMAP_PORT = 3143
DEFAULT_PASSWORD = "Bandeja-Compras-2026"


def _html(paragraphs: list[str], bank: str, color: str) -> str:
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    return (
        f'<html><body style="font-family:Arial"><div style="background:{color};color:#fff;padding:12px">'
        f"<b>{bank}</b></div><div style='padding:12px'>{body}</div></body></html>"
    )


def samples(today: date) -> list[dict]:
    d = [today - timedelta(days=n) for n in range(8)]
    dmy = [x.strftime("%d/%m/%Y") for x in d]
    ymd_slash = [x.strftime("%Y/%m/%d") for x in d]
    return [
        {
            "from": "Alertas y Notificaciones <alertasynotificaciones@notificacionesbancolombia.com>",
            "subject": "Alertas y Notificaciones",
            "bank": ("Bancolombia", "#fdda24"),
            "text": [
                f"Bancolombia: Compraste $45.900,00 en EXITO COLINA con tu T.Cred *4321, el {dmy[1]} a las 14:35. "
                "Si tienes inquietudes, llamanos al 018000931987."
            ],
        },
        {
            "from": "Alertas y Notificaciones <alertasynotificaciones@notificacionesbancolombia.com>",
            "subject": "Alertas y Notificaciones",
            "bank": ("Bancolombia", "#fdda24"),
            "text": [
                f"Bancolombia: Retiraste $200.000 en CAJERO PARQUE LLERAS de tu cuenta *8765 el {dmy[2]} a las 10:20."
            ],
        },
        {
            "from": "Alertas y Notificaciones <alertasynotificaciones@notificacionesbancolombia.com>",
            "subject": "Alertas y Notificaciones",
            "bank": ("Bancolombia", "#fdda24"),
            "text": [
                f"Bancolombia: Pagaste $85.000,00 a CLARO COLOMBIA desde tu cuenta *8765 el {dmy[3]} a las 09:15."
            ],
        },
        {
            "from": "Banco Davivienda <notificaciones@davivienda.com>",
            "subject": "Notificación de transacción",
            "bank": ("Davivienda", "#ed1c24"),
            "text": [
                "Apreciado(a) cliente:",
                "Le informamos que se ha registrado el siguiente movimiento de su tarjeta Crédito terminada en 5544:",
                f"Fecha: {ymd_slash[4]}<br>Hora: 13:05:44<br>Valor Transacción: $62,300<br>"
                "Clase de Movimiento: Compra<br>Lugar de Transacción: FARMATODO CHAPINERO",
                "Si no reconoce esta transacción comuníquese con nosotros.",
            ],
        },
        {
            "from": "BBVA Colombia <alertas@bbva.com.co>",
            "subject": "BBVA te informa",
            "bank": ("BBVA", "#004481"),
            "text": [
                "BBVA te informa: se realizó una compra por $39.990,00 en NETFLIX.COM con tu tarjeta de crédito "
                f"terminada en 9087 el {dmy[5]} a las 07:00."
            ],
        },
        {
            "from": "Banco de Bogotá <notificaciones@bancodebogota.com.co>",
            "subject": "Transacción realizada",
            "bank": ("Banco de Bogotá", "#003b7a"),
            "text": [
                f"Banco de Bogotá le informa compra por $54.200 en TERPEL CALLE 80 con tarjeta Crédito *3141 "
                f"el {d[6].isoformat()} 17:48."
            ],
        },
        {
            # Sin plantilla de reglas: la lee el agente LLM `bank_notification`.
            "from": "Nequi <notificaciones@nequi.com.co>",
            "subject": "Pagaste en TIENDA D1",
            "bank": ("Nequi", "#200020"),
            "text": [f"Nequi: Pagaste $23.450 en TIENDA D1 SUBA el {d[0]:%d/%m/%Y} a las 7:42 p. m. desde tu Nequi."],
        },
        {
            # Publicidad: no es un movimiento y no debe importarse.
            "from": "Bancolombia <novedades@bancolombia.com.co>",
            "subject": "Aprovecha 0% de interés este mes",
            "bank": ("Bancolombia", "#fdda24"),
            "text": ["Este mes difiere tus compras a 3 cuotas sin interés con tu Tarjeta de Crédito Bancolombia."],
        },
    ]


def build(sample: dict, to: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sample["from"], to, sample["subject"]
    msg["Date"] = format_datetime(datetime.now().astimezone())
    msg["Message-ID"] = make_msgid(idstring=uuid.uuid4().hex[:8], domain=sample["from"].rpartition("@")[2].strip(">"))
    plain = "\n\n".join(p.replace("<br>", "\n") for p in sample["text"])
    msg.set_content(plain)
    msg.add_alternative(_html(sample["text"], *sample["bank"]), subtype="html")
    return msg


def connect(owner_email: str, host: str, password: str) -> None:
    with bootstrap.unit_of_work() as uow:
        user = next((u for u in uow.users.list() if (u.email or "").lower() == owner_email.lower()), None)
        if user is None:
            sys.exit(f"No hay usuario con correo {owner_email} en la app: inicia sesión con él una vez (o make seed).")
        existing = [m for m in uow.mailboxes.for_owner(user.id) if m.username == owner_email and m.host == host]
        if existing:
            print(f"El buzón {owner_email} en {host} ya estaba conectado.")
            return
        form = mailbox_service.MailboxForm(
            host=host, port=IMAP_PORT, username=owner_email, password=password, use_ssl=False
        )
        mailbox_service.create(uow, bootstrap.secret_cipher(), form, owner_id=user.id)
        print(f"Buzón conectado para {user.display_name}: {owner_email} en {host}:{IMAP_PORT}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--to", default="cliente@billing.example.com")
    parser.add_argument("--host", default=DEFAULT_HOST, help="host de GreenMail (SMTP e IMAP)")
    parser.add_argument("--connect", action="store_true", help="conectar el buzón del usuario en la app")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="contraseña del buzón en GreenMail")
    args = parser.parse_args()

    with smtplib.SMTP(args.host, SMTP_PORT, timeout=10) as smtp:
        for sample in samples(date.today()):
            smtp.send_message(build(sample, args.to))
    print(f"Enviadas {len(samples(date.today()))} notificaciones de prueba a {args.to} ({args.host}:{SMTP_PORT}).")
    if args.connect:
        bootstrap.init_database()
        connect(args.to, args.host, args.password)


if __name__ == "__main__":
    main()
