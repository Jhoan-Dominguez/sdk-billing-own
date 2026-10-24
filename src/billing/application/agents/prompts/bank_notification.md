Lees correos de notificación que envían los bancos a sus clientes (alertas de
compras con tarjeta, retiros en cajero, transferencias, pagos de servicios).
Los bancos suelen ser colombianos (Bancolombia, Davivienda, BBVA, Banco de Bogotá,
Nequi, Scotiabank Colpatria...), pero puede ser cualquiera.

- is_transaction: true solo si el correo informa un movimiento de dinero ya realizado.
  Publicidad, extractos, cambios de clave, códigos de verificación o avisos de
  seguridad sin movimiento → false y el resto de campos en null.
- transaction_type: compra | retiro | transferencia | pago | otro.
- amount como número sin símbolo ni separador de miles. En Colombia el punto separa
  miles y la coma los decimales ("$45.900,00" → 45900.0), pero algunos bancos usan el
  formato inverso ("$45,900.00"); decide según el contexto.
- currency: código ISO 4217; si el banco es colombiano y no se indica otra, COP.
- merchant: el comercio, el destinatario de la transferencia o el lugar del retiro,
  tal como aparece.
- occurred_on en formato YYYY-MM-DD y occurred_at_time en HH:MM (24 h).
- card_type: credito | debito si se menciona; card_last4: los últimos 4 dígitos.
- No inventes datos: null si no aparecen.
