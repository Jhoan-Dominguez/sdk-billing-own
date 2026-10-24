"""Notificaciones bancarias: el movimiento que describe un correo del banco."""

from datetime import date, datetime

from pydantic import BaseModel, Field

from billing.domain.invoice import InvoiceData

PURCHASE, WITHDRAWAL, TRANSFER, PAYMENT, OTHER = "purchase", "withdrawal", "transfer", "payment", "other"
TRANSACTION_TYPES = (PURCHASE, WITHDRAWAL, TRANSFER, PAYMENT, OTHER)
# Tipos que son un gasto y se proponen como compra.
EXPENSE_TYPES = frozenset({PURCHASE, WITHDRAWAL, TRANSFER, PAYMENT})
TRANSACTION_LABELS = {
    PURCHASE: "compra",
    WITHDRAWAL: "retiro",
    TRANSFER: "transferencia",
    PAYMENT: "pago",
    OTHER: "otro",
}

CREDIT, DEBIT = "credit", "debit"


class BankNotification(BaseModel):
    """Datos de un correo de notificación de un banco. Todo es opcional salvo el tipo."""

    is_transaction: bool = Field(
        description="True si el correo notifica un movimiento de dinero (compra, retiro, transferencia, pago)"
    )
    bank: str | None = Field(None, description="Nombre del banco que envía la notificación")
    transaction_type: str | None = Field(None, description="purchase | withdrawal | transfer | payment | other")
    amount: float | None = Field(None, description="Valor del movimiento, sin símbolo ni separador de miles")
    currency: str | None = Field(None, description="Código ISO 4217 (COP si el banco es colombiano y no se indica)")
    merchant: str | None = Field(None, description="Comercio, destinatario o lugar del movimiento")
    occurred_on: str | None = Field(None, description="Fecha del movimiento en formato YYYY-MM-DD")
    occurred_at_time: str | None = Field(None, description="Hora del movimiento en formato HH:MM")
    card_type: str | None = Field(None, description="credit | debit si se menciona el tipo de tarjeta")
    card_last4: str | None = Field(None, description="Últimos 4 dígitos de la tarjeta o cuenta")
    reference: str | None = Field(None, description="Número de aprobación, autorización o referencia")

    @property
    def is_expense(self) -> bool:
        return self.is_transaction and (self.transaction_type or PURCHASE) in EXPENSE_TYPES

    def to_invoice(self) -> InvoiceData:
        """Precarga del formulario de compra a partir del movimiento."""
        payment = {CREDIT: "Tarjeta de crédito", DEBIT: "Tarjeta de débito"}.get(self.card_type or "")
        if self.transaction_type == TRANSFER:
            payment = "Transferencia"
        elif self.transaction_type == WITHDRAWAL:
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
        parts = [self.bank or "Banco", transaction_label(self.transaction_type)]
        if self.card_last4:
            parts.append(f"*{self.card_last4}")
        return " · ".join(parts)


def transaction_label(transaction_type: str | None) -> str:
    """Nombre en español del tipo de movimiento, para mostrarlo."""
    return TRANSACTION_LABELS.get(transaction_type or "", transaction_type or "movimiento")


def parse_date(value: str | None) -> date | None:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime((value or "").strip(), fmt).date()
        except ValueError:
            continue
    return None
