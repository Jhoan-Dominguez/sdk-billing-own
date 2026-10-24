"""Notificaciones bancarias: el movimiento que describe un correo del banco."""

from datetime import date, datetime

from pydantic import BaseModel, Field

from billing.domain.invoice import InvoiceData

TRANSACTION_TYPES = ("compra", "retiro", "transferencia", "pago", "otro")
# Tipos que son un gasto y se proponen como compra.
EXPENSE_TYPES = frozenset({"compra", "retiro", "transferencia", "pago"})


class BankNotification(BaseModel):
    """Datos de un correo de notificación de un banco. Todo es opcional salvo el tipo."""

    is_transaction: bool = Field(
        description="True si el correo notifica un movimiento de dinero (compra, retiro, transferencia, pago)"
    )
    bank: str | None = Field(None, description="Nombre del banco que envía la notificación")
    transaction_type: str | None = Field(None, description="compra | retiro | transferencia | pago | otro")
    amount: float | None = Field(None, description="Valor del movimiento, sin símbolo ni separador de miles")
    currency: str | None = Field(None, description="Código ISO 4217 (COP si el banco es colombiano y no se indica)")
    merchant: str | None = Field(None, description="Comercio, destinatario o lugar del movimiento")
    occurred_on: str | None = Field(None, description="Fecha del movimiento en formato YYYY-MM-DD")
    occurred_at_time: str | None = Field(None, description="Hora del movimiento en formato HH:MM")
    card_type: str | None = Field(None, description="credito | debito si se menciona el tipo de tarjeta")
    card_last4: str | None = Field(None, description="Últimos 4 dígitos de la tarjeta o cuenta")
    reference: str | None = Field(None, description="Número de aprobación, autorización o referencia")

    @property
    def is_expense(self) -> bool:
        return self.is_transaction and (self.transaction_type or "compra") in EXPENSE_TYPES

    def to_invoice(self) -> InvoiceData:
        """Precarga del formulario de compra a partir del movimiento."""
        payment = {"credito": "Tarjeta de crédito", "debito": "Tarjeta de débito"}.get(self.card_type or "")
        if self.transaction_type == "transferencia":
            payment = "Transferencia"
        elif self.transaction_type == "retiro":
            payment = "Efectivo"
        return InvoiceData(
            vendor=self.merchant,
            invoice_number=self.reference,
            purchase_date=self.occurred_on,
            currency=(self.currency or "").upper() or None,
            total=self.amount,
            payment_method=payment,
        )

    def summary(self) -> str:
        parts = [self.bank or "Banco", self.transaction_type or "movimiento"]
        if self.card_last4:
            parts.append(f"*{self.card_last4}")
        return " · ".join(parts)


def parse_date(value: str | None) -> date | None:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime((value or "").strip(), fmt).date()
        except ValueError:
            continue
    return None
