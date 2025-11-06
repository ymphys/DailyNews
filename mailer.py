import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import Optional

from digest_utils import LOGGER
import markdown

SMTP_HOST = "smtp.qq.com"
SMTP_PORT_TLS = 587


def send_digest_via_email(
    markdown_path: Path,
    subject: str,
    *,
    from_addr: Optional[str] = None,
    to_addr: Optional[str] = None,
) -> None:
    from_addr = from_addr or os.environ.get("DAILYNEWS_EMAIL_FROM")
    raw_to = to_addr or os.environ.get("DAILYNEWS_EMAIL_TO", "")
    recipients = [addr.strip() for addr in raw_to.split(",") if addr and addr.strip()]
    app_pw = os.environ.get("DAILYNEWS_EMAIL_APP_PW")

    if not (from_addr and recipients and app_pw):
        LOGGER.warning("Email env vars missing; skipping email send.")
        return

    markdown_text = markdown_path.read_text(encoding="utf-8")
    html_body = markdown.markdown(markdown_text)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)
    msg.set_content(markdown_text)
    msg.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()

    smtp: Optional[smtplib.SMTP] = None
    try:
        smtp = smtplib.SMTP(SMTP_HOST, SMTP_PORT_TLS)
        smtp.ehlo()
        smtp.starttls(context=context)
        smtp.ehlo()
        smtp.login(from_addr, app_pw)
        smtp.send_message(msg, to_addrs=recipients)
        try:
            smtp.quit()
        except smtplib.SMTPResponseException as quit_exc:
            if quit_exc.smtp_code != -1:
                raise
            LOGGER.debug("SMTP quit() returned (-1, b'\\x00\\x00\\x00'); ignoring.")
        LOGGER.info("Sent digest email via QQ SMTP to %s.", ", ".join(recipients))
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
