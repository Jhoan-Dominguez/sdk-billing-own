<#--
  Diseño común de los correos: cabecera verde con la marca, tarjeta blanca y pie.
  Los textos (messages_es.properties) pasan por kcSanitize, que quita estilos en
  línea: por eso todo el estilo vive aquí. Mantener en sintonía con
  src/billing/infrastructure/mail/templates/layout.html.
-->
<#macro emailLayout>
<!doctype html>
<html lang="${locale.language}" dir="${(ltr)?then('ltr','rtl')}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body { margin: 0; padding: 0; background: #f4f6f9; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; color: #213547; }
  .cp-wrap { padding: 32px 16px; }
  .cp-card { max-width: 560px; margin: 0 auto; background: #ffffff; border: 1px solid #dde3ea; border-radius: 12px; overflow: hidden; }
  .cp-head { background: #42b883; color: #ffffff; padding: 18px 28px; font-size: 18px; font-weight: 700; }
  .cp-body { padding: 28px; font-size: 15px; line-height: 1.6; }
  .cp-body a { display: inline-block; margin: 8px 0; padding: 12px 22px; background: #42b883; color: #ffffff !important; border-radius: 8px; font-weight: 600; text-decoration: none; }
  .cp-foot { max-width: 560px; margin: 16px auto 0; color: #5b6b78; font-size: 12px; text-align: center; }
</style>
</head>
<body>
<div class="cp-wrap">
  <div class="cp-card">
    <div class="cp-head">Registro de compras</div>
    <div class="cp-body">
      <#nested>
    </div>
  </div>
  <p class="cp-foot">Recibes este correo por una acción en tu cuenta de Registro de compras. Si no fuiste tú, ignóralo.</p>
</div>
</body>
</html>
</#macro>
