"""Outbound email.

Two backends, chosen by whether `SMTP_HOST` is set: real SMTP, or a log line.
The log backend means development and the test suite never need a mail server,
and a misconfigured production host degrades to "the mail was not sent" rather
than "the password reset crashed".

Sending never raises into a request. A reset whose email fails still succeeds
as far as the caller is concerned — the token is valid either way — and the
failure is logged. That also keeps the unauthenticated reset endpoint from
leaking which addresses exist through an error or a delay.
"""

from __future__ import annotations

import datetime as dt
import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from app.config import settings
from app.i18n import Translator

log = logging.getLogger("nightshift.mail")

# Inlined because email clients discard <style> blocks and know nothing of CSS
# variables. Kept to the palette the app already uses.
INK = "#16202e"
MUTED = "#5b6b80"
ACCENT = "#0f766e"
LINE = "#dde3ec"


def _shell(t: Translator, *, title: str, body: str) -> str:
    align = "right" if t.dir == "rtl" else "left"
    return f"""\
<!doctype html>
<html lang="{t.lang}" dir="{t.dir}">
<body style="margin:0;padding:24px;background:#f4f6fa;
             font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
             color:{INK};direction:{t.dir};text-align:{align}">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0"
         style="max-width:560px;margin:0 auto;background:#fff;border:1px solid {LINE};
                border-radius:12px;width:100%">
    <tr><td style="padding:28px 28px 8px">
      <div style="font-size:13px;letter-spacing:.08em;text-transform:uppercase;
                  color:{ACCENT};font-weight:700">{settings.app_name}</div>
      <h1 style="margin:10px 0 0;font-size:21px;line-height:1.3;font-weight:650">{title}</h1>
    </td></tr>
    <tr><td style="padding:4px 28px 28px;font-size:15px;line-height:1.6;color:{INK}">
      {body}
    </td></tr>
  </table>
</body>
</html>"""


def _button(t: Translator, url: str, label: str) -> str:
    return f"""\
<p style="margin:22px 0">
  <a href="{url}" style="display:inline-block;background:{ACCENT};color:#fff;
     text-decoration:none;padding:11px 20px;border-radius:8px;font-weight:600">{label}</a>
</p>
<p style="margin:16px 0 4px;font-size:13px;color:{MUTED}">{t('mail.linkFallback')}</p>
<p style="margin:0;font-size:13px;word-break:break-all"><a href="{url}"
   style="color:{ACCENT}">{url}</a></p>"""


def _para(text: str, *, muted: bool = False) -> str:
    colour = MUTED if muted else INK
    size = "13px" if muted else "15px"
    return f'<p style="margin:14px 0 0;color:{colour};font-size:{size}">{text}</p>'


# ───────────────────────────── transport ─────────────────────────────


def send(to: str, subject: str, text: str, html: str | None = None) -> bool:
    """Deliver one message. Returns whether it actually went out."""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr(
        (settings.mail_from_name or settings.app_name, settings.mail_sender)
    )
    message["To"] = to
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")

    if not settings.mail_enabled:
        # No transport configured: leave a trace a developer can act on. The
        # body carries the link, which is the whole point of these messages.
        log.info("email not sent (no SMTP_HOST) to=%s subject=%s\n%s", to, subject, text)
        return False

    try:
        if settings.smtp_ssl:
            client = smtplib.SMTP_SSL(
                settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout
            )
        else:
            client = smtplib.SMTP(
                settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout
            )
        with client:
            client.ehlo()
            if settings.smtp_starttls and not settings.smtp_ssl:
                client.starttls()
                client.ehlo()
            if settings.smtp_user:
                client.login(settings.smtp_user, settings.smtp_password)
            client.send_message(message)
        log.info("email sent to=%s subject=%s", to, subject)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        # A mail server that is down must not take a password reset with it.
        log.warning("email failed to=%s subject=%s error=%s", to, subject, exc)
        return False


# ───────────────────────────── messages ─────────────────────────────


def send_password_reset(*, to: str, name: str, url: str, lang: str = "en") -> bool:
    t = Translator(lang)
    hours = t.hours(max(1, round(settings.password_reset_ttl / 3600)))
    subject = t("mail.resetSubject", app=settings.app_name)
    intro = t("mail.resetIntro", hours=hours)
    ignore = t("mail.resetIgnore")

    text = "\n\n".join([
        t("mail.greeting", name=name),
        intro,
        url,
        ignore,
    ])
    html = _shell(
        t,
        title=t("mail.resetTitle"),
        body=(
            _para(t("mail.greeting", name=name))
            + _para(intro)
            + _button(t, url, t("mail.resetAction"))
            + _para(ignore, muted=True)
        ),
    )
    return send(to, subject, text, html)


def send_invitation(
    *,
    to: str,
    department: str,
    inviter: str,
    role,
    url: str,
    expires_at: dt.datetime | None = None,
    lang: str = "en",
) -> bool:
    t = Translator(lang)
    subject = t("mail.inviteSubject", inviter=inviter, department=department)
    intro = t(
        "mail.inviteIntro",
        inviter=inviter, department=department, app=settings.app_name, role=t.role(role),
    )
    expiry = (
        t("mail.inviteExpiry", date=t.long_date(expires_at.date())) if expires_at else ""
    )

    text = "\n\n".join(x for x in [intro, url, expiry] if x)
    html = _shell(
        t,
        title=t("mail.inviteTitle", department=department),
        body=(
            _para(intro)
            + _button(t, url, t("mail.inviteAction"))
            + (_para(expiry, muted=True) if expiry else "")
        ),
    )
    return send(to, subject, text, html)


def base_url(request=None) -> str:
    """Where links in email should point.

    `PUBLIC_URL` wins, because behind a proxy the request's own host is the
    internal one. Falls back to the request, then to localhost.
    """
    if settings.public_url:
        return settings.public_url.rstrip("/")
    if request is not None:
        return str(request.base_url).rstrip("/")
    return "http://localhost:8000"


__all__ = ["send", "send_password_reset", "send_invitation", "base_url"]
