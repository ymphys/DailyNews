import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Iterable, List, Optional, Union, Dict, Any

from digest_utils import LOGGER
import markdown

SMTP_HOST = "smtp.qq.com"
SMTP_PORT_TLS = 587

RecipientArg = Union[str, Dict[str, Any]]


def _normalize_recipients(
    recipients: Optional[Iterable[RecipientArg]],
) -> List[Dict[str, Optional[str]]]:
    normalized: List[Dict[str, Optional[str]]] = []
    if not recipients:
        return normalized
    for entry in recipients:
        if isinstance(entry, str):
            email = entry.strip()
            if email:
                normalized.append({"email": email, "name": None})
            continue
        if isinstance(entry, dict):
            email = entry.get("email", "")
            name = entry.get("name")
            if isinstance(email, str) and email.strip():
                normalized.append({"email": email.strip(), "name": name if isinstance(name, str) else None})
            continue
    return normalized


def _collect_env_recipients(to_addr: Optional[str]) -> List[str]:
    raw_to = to_addr or os.environ.get("DAILYNEWS_EMAIL_TO", "")
    return [addr.strip() for addr in raw_to.split(",") if addr and addr.strip()]


def send_digest_via_email(
    markdown_path: Path,
    subject: str,
    *,
    from_addr: Optional[str] = None,
    recipients: Optional[Iterable[RecipientArg]] = None,
    to_addr: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> None:
    from_addr = from_addr or os.environ.get("DAILYNEWS_EMAIL_FROM")
    env_recipients = _collect_env_recipients(to_addr)
    normalized = _normalize_recipients(recipients)

    if normalized:
        send_to = [item["email"] for item in normalized if item.get("email")]
        header_recipients = [
            formataddr((item["name"], item["email"])) if item.get("name") else item["email"]
            for item in normalized
            if item.get("email")
        ]
    else:
        send_to = env_recipients
        header_recipients = env_recipients

    app_pw = os.environ.get("DAILYNEWS_EMAIL_APP_PW")

    if not (from_addr and send_to and app_pw):
        LOGGER.warning("Email configuration incomplete; skipping email send (from=%s, recipients=%s).", from_addr, send_to)
        return

    markdown_text = markdown_path.read_text(encoding="utf-8")
    html_body = markdown.markdown(markdown_text)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(header_recipients)
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(markdown_text)
    msg.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()

    dry_run = os.environ.get("DAILYNEWS_EMAIL_DRY_RUN")
    if dry_run:
        LOGGER.info("Dry run enabled; skipping SMTP send to %s.", ", ".join(send_to))
        return

    smtp: Optional[smtplib.SMTP] = None
    try:
        smtp = smtplib.SMTP(SMTP_HOST, SMTP_PORT_TLS)
        smtp.ehlo()
        smtp.starttls(context=context)
        smtp.ehlo()
        smtp.login(from_addr, app_pw)
        smtp.send_message(msg, to_addrs=send_to)
        try:
            smtp.quit()
        except smtplib.SMTPResponseException as quit_exc:
            if quit_exc.smtp_code != -1:
                raise
            LOGGER.debug("SMTP quit() returned (-1, b'\\x00\\x00\\x00'); ignoring.")
        LOGGER.info("Sent digest email to %s.", ", ".join(send_to))
    except smtplib.SMTPResponseException as exc:
        if exc.smtp_code == -1:
            LOGGER.warning("SMTP connection closed unexpectedly after send; message likely delivered.")
        else:
            LOGGER.exception("Failed to send digest email: %s", exc)
    except Exception as exc:
        LOGGER.exception("Failed to send digest email: %s", exc)
    finally:
        if smtp is not None:
            try:
                smtp.close()
            except Exception:
                pass


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Send a Markdown file via email using the configured SMTP settings.")
    parser.add_argument("markdown_path", help="Path to the Markdown file to send.")
    parser.add_argument("--subject", default="DailyNews Digest Test", help="Email subject line.")
    parser.add_argument("--from", dest="from_addr", help="Override DAILYNEWS_EMAIL_FROM")
    parser.add_argument("--to", dest="to_addr", help="Override DAILYNEWS_EMAIL_TO")
    args = parser.parse_args()

    send_digest_via_email(
        Path(args.markdown_path),
        args.subject,
        from_addr=args.from_addr,
        to_addr=args.to_addr,
    )
