"""Plantillas de reglas para notificaciones de bancos colombianos.

Cada banco tiene sus remitentes y una lista de patrones (expresiones regulares con
grupos con nombre). Son rápidas, gratis y sin red; lo que ninguna plantilla reconoce
lo lee el agente LLM `bank_notification` (ver bank.py).

Los textos de ejemplo de cada patrón siguen el formato habitual de las alertas de
cada banco; los bancos los cambian con el tiempo, así que si una alerta real deja de
reconocerse basta con ajustar o añadir un patrón aquí (docs/servicios/correos-bancarios.md).

Grupos que entiende `match()`:
  amount (obligatorio), merchant, date, time, last4, card (crédito/débito), currency
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from billing.domain.bank import BankNotification
from billing.infrastructure.extraction.regex import parse_amount

_AMOUNT = r"(?:COP|USD|\$)?\s?(?P<amount>\d[\d.,]*\d|\d)"
_DATE_DMY = r"(?P<date>\d{1,2}/\d{1,2}/\d{4})"
_DATE_YMD = r"(?P<date>\d{4}[/-]\d{1,2}[/-]\d{1,2})"
_CARD = r"(?P<card>T\.?\s?Cred|T\.?\s?Deb)\w*"
_TIME = r"(?P<time>\d{1,2}:\d{2})(?::\d{2})?"
_MERCHANT = r"(?P<merchant>[A-Z0-9*][\w*&.\-' ]{1,60}?)"


@dataclass(frozen=True)
class Pattern:
    transaction_type: str
    regex: re.Pattern
    example: str  # alerta de ejemplo que el patrón debe reconocer (ver docs y scripts/send_bank_samples.py)


@dataclass(frozen=True)
class BankTemplate:
    bank: str
    senders: tuple[str, ...]  # dominios o direcciones del remitente
    patterns: tuple[Pattern, ...]
    keyword: str  # aparece en el texto de sus alertas (para correos reenviados)


def _p(transaction_type: str, regex: str, example: str) -> Pattern:
    # DOTALL: algunos bancos reparten los datos en varias líneas (tablas HTML).
    return Pattern(transaction_type, re.compile(regex, re.I | re.S), example)


TEMPLATES: tuple[BankTemplate, ...] = (
    BankTemplate(
        bank="Bancolombia",
        senders=("notificacionesbancolombia.com", "bancolombia.com.co"),
        keyword="bancolombia",
        patterns=(
            _p(
                "compra",
                rf"Compraste {_AMOUNT} en {_MERCHANT} con tu {_CARD} \*(?P<last4>\d{{4}}),? "
                rf"el {_DATE_DMY} a las {_TIME}",
                "Bancolombia: Compraste $45.900,00 en EXITO COLINA con tu T.Cred *4321, el 12/03/2026 a las 14:35. "
                "Si tienes inquietudes, llamanos al 018000931987.",
            ),
            _p(
                "compra",
                rf"le informa Compra por {_AMOUNT} en {_MERCHANT} {_TIME}\.? {_DATE_DMY} "
                rf"{_CARD} \*(?P<last4>\d{{4}})",
                "Bancolombia le informa Compra por $128.500,00 en RAPPI COLOMBIA 20:11. 14/03/2026 T.Deb *8765. "
                "Inquietudes al 6045109095.",
            ),
            _p(
                "retiro",
                rf"Retiraste {_AMOUNT} en {_MERCHANT} de tu cuenta \*(?P<last4>\d{{4}}) el {_DATE_DMY} a las {_TIME}",
                "Bancolombia: Retiraste $200.000 en CAJERO PARQUE LLERAS de tu cuenta *8765 el 15/03/2026 a las 10:20.",
            ),
            _p(
                "transferencia",
                rf"Transferiste {_AMOUNT} desde tu cuenta \*(?P<last4>\d{{4}}) a (?:la cuenta )?{_MERCHANT} "
                rf"el {_DATE_DMY} a las {_TIME}",
                "Bancolombia: Transferiste $150.000,00 desde tu cuenta *8765 a la cuenta *1122 el 16/03/2026 "
                "a las 18:02.",
            ),
            _p(
                "pago",
                rf"Pagaste {_AMOUNT} a {_MERCHANT} desde tu (?:cuenta|producto) \*(?P<last4>\d{{4}}) "
                rf"el {_DATE_DMY} a las {_TIME}",
                "Bancolombia: Pagaste $85.000,00 a CLARO COLOMBIA desde tu cuenta *8765 el 17/03/2026 a las 09:15.",
            ),
        ),
    ),
    BankTemplate(
        bank="Davivienda",
        senders=("davivienda.com",),
        keyword="davivienda",
        patterns=(
            _p(
                "compra",
                rf"tarjeta (?P<card>Cr[eé]dito|D[eé]bito) terminada en (?P<last4>\d{{4}}).*?"
                rf"Fecha:\s*{_DATE_YMD}.*?Hora:\s*{_TIME}.*?Valor Transacci[oó]n:\s*{_AMOUNT}.*?"
                rf"Clase de Movimiento:\s*Compra.*?Lugar de Transacci[oó]n:\s*{_MERCHANT}\s*(?:$|\n|Si |Cordialmente)",
                "Apreciado(a) cliente: Le informamos que se ha registrado el siguiente movimiento de su "
                "tarjeta Crédito terminada en 5544:\nFecha: 2026/03/18\nHora: 13:05:44\nValor Transacción: $62,300\n"
                "Clase de Movimiento: Compra\nLugar de Transacción: FARMATODO CHAPINERO\n"
                "Si no reconoce esta transacción comuníquese con nosotros.",
            ),
            _p(
                "retiro",
                rf"terminada en (?P<last4>\d{{4}}).*?"
                rf"Fecha:\s*{_DATE_YMD}.*?Hora:\s*{_TIME}.*?Valor Transacci[oó]n:\s*{_AMOUNT}.*?"
                rf"Clase de Movimiento:\s*Retiro.*?Lugar de Transacci[oó]n:\s*{_MERCHANT}\s*(?:$|\n|Si |Cordialmente)",
                "Apreciado(a) cliente: Le informamos que se ha registrado el siguiente movimiento de su "
                "cuenta de ahorros terminada en 7788:\nFecha: 2026/03/19\nHora: 08:40:02\nValor Transacción: $300,000\n"
                "Clase de Movimiento: Retiro\nLugar de Transacción: CAJERO DAVIVIENDA UNICENTRO\n"
                "Si no reconoce esta transacción comuníquese con nosotros.",
            ),
        ),
    ),
    BankTemplate(
        bank="BBVA",
        senders=("bbva.com.co", "bbva.com"),
        keyword="bbva",
        patterns=(
            _p(
                "compra",
                rf"se realiz[oó] una compra por {_AMOUNT} en {_MERCHANT} con tu tarjeta de "
                rf"(?P<card>cr[eé]dito|d[eé]bito) terminada en (?P<last4>\d{{4}}) el {_DATE_DMY} a las {_TIME}",
                "BBVA te informa: se realizó una compra por $39.990,00 en NETFLIX.COM con tu tarjeta de crédito "
                "terminada en 9087 el 20/03/2026 a las 07:00.",
            ),
        ),
    ),
    BankTemplate(
        bank="Banco de Bogotá",
        senders=("bancodebogota.com.co", "bancodebogota.com"),
        keyword="banco de bogota",
        patterns=(
            _p(
                "compra",
                rf"compra por {_AMOUNT} en {_MERCHANT} con (?:su )?tarjeta (?P<card>Cr[eé]dito|D[eé]bito) "
                rf"\*(?P<last4>\d{{4}}) el {_DATE_YMD} {_TIME}",
                "Banco de Bogotá le informa compra por $54.200 en TERPEL CALLE 80 con tarjeta Crédito *3141 "
                "el 2026-03-21 17:48.",
            ),
        ),
    ),
)


def normalize(text: str) -> str:
    """Sin tildes (para patrones más simples) y con espacios colapsados por línea."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return "\n".join(re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.splitlines())


def templates_for(sender: str, text: str) -> list[BankTemplate]:
    """Plantillas del banco que envía el correo; si el remitente no es de un banco
    conocido (correo reenviado), las de los bancos que se mencionan en el texto."""
    sender = sender.lower()
    domain = sender.rpartition("@")[2]
    by_sender = [t for t in TEMPLATES if any(domain == s or domain.endswith("." + s) or sender == s for s in t.senders)]
    if by_sender:
        return by_sender
    lowered = normalize(text).lower()
    return [t for t in TEMPLATES if t.keyword in lowered]


def is_bank_sender(sender: str) -> bool:
    domain = sender.lower().rpartition("@")[2]
    return any(domain == s or domain.endswith("." + s) for t in TEMPLATES for s in t.senders)


def _card_type(value: str | None) -> str | None:
    value = (value or "").lower().replace(".", "").replace(" ", "")
    if value.startswith(("tcred", "cred", "cré")):
        return "credito"
    if value.startswith(("tdeb", "deb", "déb")):
        return "debito"
    return None


def _iso_date(value: str | None) -> str | None:
    for fmt in ("%d/%m/%Y", "%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value or "", fmt).date().isoformat()
        except ValueError:
            continue
    return None


def match(text: str, sender: str = "") -> BankNotification | None:
    """La notificación reconocida por alguna plantilla, o None."""
    clean = normalize(text)
    for template in templates_for(sender, text):
        for pattern in template.patterns:
            m = pattern.regex.search(clean)
            if not m:
                continue
            groups = m.groupdict()
            amount = parse_amount(groups["amount"])
            if amount is None:
                continue
            hour = groups.get("time")
            merchant = (groups.get("merchant") or "").strip(" .,") or None
            if merchant and merchant.startswith("*"):
                merchant = f"Cuenta {merchant}"  # transferencia a una cuenta sin nombre
            return BankNotification(
                is_transaction=True,
                bank=template.bank,
                transaction_type=pattern.transaction_type,
                amount=amount,
                currency=(groups.get("currency") or "COP").upper(),
                merchant=merchant,
                occurred_on=_iso_date(groups.get("date")),
                occurred_at_time=f"{int(hour.split(':')[0]):02d}:{hour.split(':')[1]}" if hour else None,
                card_type=_card_type(groups.get("card")),
                card_last4=groups.get("last4"),
            )
    return None
