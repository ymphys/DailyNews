import os
import smtplib
import ssl
import mimetypes
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Iterable, List, Optional, Union, Dict, Any

import markdown
from bs4 import BeautifulSoup

from digest_utils import DIGEST_DIR, LOGGER

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


def _collect_story_sections(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    headings = soup.find_all("h3")
    for idx, heading in enumerate(headings):
        content_nodes = []
        sibling = heading.next_sibling
        while sibling and getattr(sibling, "name", None) != "h3":
            next_sib = sibling.next_sibling
            content_nodes.append(sibling)
            sibling = next_sib
        snippet_html = "".join(str(node) for node in [heading] + content_nodes)
        sections.append(
            {
                "index": idx,
                "h3": heading,
                "content_nodes": content_nodes,
                "image_path": None,
                "image_cid": f"story-{idx+1:02d}@newsdigest",
                "html": snippet_html,
            }
        )
    return sections


def _story_images_output_dir(markdown_path: Path) -> Path:
    slug = markdown_path.stem.replace(" ", "_") or "digest"
    return DIGEST_DIR / slug


def _render_story_card_html(section_html: str) -> str:
    style = """
    body {
      margin: 0;
      background: #f2f4f8;
      font-family: 'PingFang SC', 'Noto Sans SC', 'Helvetica Neue', sans-serif;
    }
    .story-card {
      max-width: 1040px;
      margin: 32px auto;
      padding: 34px 38px;
      background: #ffffff;
      border-radius: 18px;
      box-shadow: 0 20px 45px rgba(15, 23, 42, 0.15);
    }
    h3 {
      font-size: 1.9rem;
      margin-bottom: 0.75rem;
      color: #111827;
    }
    p, li {
      color: #1f2937;
      line-height: 1.7;
      font-size: 1rem;
    }
    ul {
      margin: 0 0 0 1rem;
      padding: 0;
    }
    li {
      margin-bottom: 0.35rem;
    }
    """
    return (
        "<!doctype html>"
        "<html>"
        "<head>"
        "<meta charset=\"utf-8\"/>"
        "<title>Story Snapshot</title>"
        f"<style>{style}</style>"
        "</head>"
        "<body>"
        "<div class=\"story-card\">"
        f"{section_html}"
        "</div>"
        "</body>"
        "</html>"
    )

def _build_image_email_body(sections: List[Dict[str, Any]]) -> str:
    if not sections:
        return "<p>No story images available.</p>"
    parts: List[str] = [
        "<div style=\"background:#f9fafb;padding:12px;\">",
        "<div style=\"max-width:840px;margin:0 auto;\">",
    ]
    for section in sections:
        image_path = section.get("image_path")
        if not image_path:
            continue
        label = section["h3"].get_text().strip()
        parts.append(
            "<div style=\"margin-bottom:24px;text-align:center;\">"
            f"<img src=\"cid:{section['image_cid']}\" alt=\"{label}\" style=\"display:block;margin:0 auto;max-width:100%;border-radius:18px;box-shadow:0 20px 40px rgba(15,23,42,.15);\"/>"
            "</div>"
        )
    parts.append("</div>")
    parts.append("</div>")
    return "\n".join(parts)


def _capture_story_images(markdown_path: Path, sections: List[Dict[str, Any]]) -> List[Path]:
    if not sections:
        return []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        LOGGER.warning(
            "Playwright is not installed; skipping story image capture (pip install playwright)."
        )
        return []

    output_dir = _story_images_output_dir(markdown_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    image_paths: List[Path] = []
    missing_sections: List[Dict[str, Any]] = []
    for section in sections:
        dest = output_dir / f"story-{section['index'] + 1:02d}.png"
        if dest.exists():
            section["image_path"] = dest
            image_paths.append(dest)
        else:
            section["image_path"] = None
            missing_sections.append(section)

    if not missing_sections:
        LOGGER.info("All story images already available in %s", output_dir)
        return image_paths

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            for section in missing_sections:
                page = browser.new_page(viewport={"width": 1200, "height": 900})
                html = _render_story_card_html(section["html"])
                page.set_content(html, wait_until="networkidle")
                dest = output_dir / f"story-{section['index'] + 1:02d}.png"
                page.screenshot(path=str(dest), full_page=True)
                image_paths.append(dest)
                section["image_path"] = dest
                page.close()
            browser.close()
    except Exception as exc:  # pragma: no cover
        LOGGER.warning("Failed to capture story images: %s", exc)
        return []

    LOGGER.info("Captured %s story images in %s", len(image_paths), output_dir)
    return image_paths

def send_digest_via_email(
    markdown_path: Path,
    subject: str,
    *,
    from_addr: Optional[str] = None,
    recipients: Optional[Iterable[RecipientArg]] = None,
    to_addr: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> List[Path]:
    from_addr = from_addr or os.environ.get("DAILYNEWS_EMAIL_FROM")
    env_recipients = _collect_env_recipients(to_addr)
    normalized = _normalize_recipients(recipients)

    if normalized:
        recipient_entries = normalized
    else:
        recipient_entries = [{"email": addr, "name": None} for addr in env_recipients]

    send_to = [entry["email"] for entry in recipient_entries if entry.get("email")]

    app_pw = os.environ.get("DAILYNEWS_EMAIL_APP_PW")

    if not (from_addr and send_to and app_pw):
        LOGGER.warning(
            "Email configuration incomplete; skipping email send (from=%s, recipients=%s).",
            from_addr,
            send_to,
        )
        return []

    markdown_text = markdown_path.read_text(encoding="utf-8")

    # 将markdown转为HTML
    html_body = markdown.markdown(markdown_text)

    soup = BeautifulSoup(html_body, "html.parser")
    story_sections = _collect_story_sections(soup)
    _capture_story_images(markdown_path, story_sections)
    html_body = _build_image_email_body(story_sections)

    dry_run = os.environ.get("DAILYNEWS_EMAIL_DRY_RUN")

    context = ssl.create_default_context()

    for entry in recipient_entries:
        email = entry.get("email")
        if not email:
            continue

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = from_addr
        recipient_header = formataddr((entry["name"], email)) if entry.get("name") else email
        msg["To"] = recipient_header
        if reply_to:
            msg["Reply-To"] = reply_to
        msg.set_content("Image digest attached; please open the HTML part to view the visuals.")
        msg.add_alternative(html_body, subtype="html")
        html_part = msg.get_body(preferencelist=("html",))
        for section in story_sections:
            image_path = section.get("image_path")
            if not image_path or not image_path.exists():
                continue
            mime_type, _ = mimetypes.guess_type(image_path)
            if mime_type and "/" in mime_type:
                maintype, subtype = mime_type.split("/", 1)
            else:
                maintype, subtype = "image", "png"
            with open(image_path, "rb") as img_fh:
                html_part.add_related(
                    img_fh.read(),
                    maintype=maintype,
                    subtype=subtype,
                    cid=f"<{section['image_cid']}>",
                )

        if dry_run:
            LOGGER.info("Dry run enabled; skipping SMTP send to %s.", email)
            continue

        smtp: Optional[smtplib.SMTP] = None
        try:
            smtp = smtplib.SMTP(SMTP_HOST, SMTP_PORT_TLS)
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(from_addr, app_pw)
            smtp.send_message(msg, to_addrs=[email])
            try:
                smtp.quit()
            except smtplib.SMTPResponseException as quit_exc:
                if quit_exc.smtp_code != -1:
                    raise
                LOGGER.debug("SMTP quit() returned (-1, b'\\x00\\x00\\x00'); ignoring.")
            LOGGER.info("Sent digest email to %s.", email)
        except smtplib.SMTPResponseException as exc:
            if exc.smtp_code == -1:
                LOGGER.warning(
                    "SMTP connection closed unexpectedly after send to %s; message likely delivered.",
                    email,
                )
            else:
                LOGGER.exception("Failed to send digest email to %s: %s", email, exc)
        except Exception as exc:
            LOGGER.exception("Failed to send digest email to %s: %s", email, exc)
        finally:
            if smtp is not None:
                try:
                    smtp.close()
                except Exception:
                    pass

    return [s["image_path"] for s in story_sections if s.get("image_path")]


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
