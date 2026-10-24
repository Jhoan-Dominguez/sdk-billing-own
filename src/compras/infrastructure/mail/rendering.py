"""Maqueta un EmailContent en texto plano y HTML con el diseño común."""

import html
from pathlib import Path
from string import Template

from compras.domain.ports.mail import EmailContent

LAYOUT = Template((Path(__file__).with_name("templates") / "layout.html").read_text(encoding="utf-8"))
BUTTON = (
    '<p><a href="{url}" style="display:inline-block;margin:8px 0;padding:12px 22px;background:#42b883;'
    'color:#ffffff;border-radius:8px;font-weight:600;text-decoration:none;">{label}</a></p>'
    '<p style="color:#5b6b78;font-size:13px;">Si el botón no funciona, copia este enlace en el navegador:<br>'
    '<span style="word-break:break-all;">{url}</span></p>'
)


def render_text(email: EmailContent) -> str:
    lines = [email.title, "", *[p + "\n" for p in email.paragraphs]]
    if email.action_url:
        lines += [f"{email.action_label or 'Abrir'}: {email.action_url}", ""]
    lines += ["--", email.footer]
    return "\n".join(lines)


def render_html(email: EmailContent) -> str:
    body = "".join(f"<p>{html.escape(p)}</p>" for p in email.paragraphs)
    if email.action_url:
        body += BUTTON.format(url=html.escape(email.action_url), label=html.escape(email.action_label or "Abrir"))
    return LAYOUT.substitute(
        subject=html.escape(email.subject),
        title=html.escape(email.title),
        body=body,
        footer=html.escape(email.footer),
    )
