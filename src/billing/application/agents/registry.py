"""Agentes de la aplicación. Para añadir uno: su esquema de salida (domain), su
prompt (prompts/*.md) y un AgentSpec aquí; aparece solo en Configuración → Agentes IA."""

from billing.application.agents.base import AgentSpec
from billing.domain.bank import BankNotification
from billing.domain.invoice import InvoiceData

INVOICE = "invoice"
BANK_NOTIFICATION = "bank_notification"

AGENTS: dict[str, AgentSpec] = {
    INVOICE: AgentSpec(
        name=INVOICE,
        label="Lector de facturas",
        description="Extrae comercio, fecha, totales, impuestos y líneas de fotos, PDFs y correos de compra.",
        output=InvoiceData,
        prompt_file="invoice.md",
    ),
    BANK_NOTIFICATION: AgentSpec(
        name=BANK_NOTIFICATION,
        label="Notificaciones bancarias",
        description=(
            "Lee los correos de alerta de los bancos (compras con tarjeta, retiros, transferencias) "
            "cuando ninguna plantilla de reglas los reconoce."
        ),
        output=BankNotification,
        prompt_file="bank_notification.md",
        max_tokens=4000,
    ),
}
