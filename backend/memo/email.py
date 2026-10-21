"""Email the memo with Resend. One request, a timeout, and a plain-words fallback.

Plain HTML + text (no tracking pixels, no images). An Idempotency-Key per call and
recipient means a double click can't send the memo twice.
"""

import hashlib
import html
import logging
import time

import httpx

from memo.builder import clock
from pipeline.events import EmailResult, Memo
from pipeline.latency import record

log = logging.getLogger("tenor.email")

RESEND_URL = "https://api.resend.com/emails"


def render_text(memo: Memo) -> str:
    lines = [memo.headline, "", memo.summary, ""]
    for s in memo.sections:
        lines.append(s.title.upper())
        if not s.items:
            lines.append(f"  {s.empty}")
        for i in s.items:
            at = f" [{clock(i.t)}]" if i.t is not None else ""
            lines.append(f"  - {i.text}{at}" + (f"\n    {i.detail}" if i.detail else ""))
        lines.append("")
    lines.append(memo.note)
    return "\n".join(lines)


def render_html(memo: Memo) -> str:
    e = html.escape
    parts = [
        "<div style=\"font-family: -apple-system, Segoe UI, Arial, sans-serif; color: #14181E; max-width: 620px; line-height: 1.5\">",
        f"<h1 style=\"font-size: 22px\">{e(memo.headline)}</h1>",
        f"<p style=\"font-size: 16px\">{e(memo.summary)}</p>",
    ]
    for s in memo.sections:
        parts.append(f"<h2 style=\"font-size: 17px; margin-top: 24px\">{e(s.title)}</h2>")
        if not s.items:
            parts.append(f"<p style=\"color: #5C6470\">{e(s.empty)}</p>")
            continue
        parts.append("<ul style=\"padding-left: 18px\">")
        for i in s.items:
            at = f" <span style=\"color: #5C6470\">({clock(i.t)})</span>" if i.t is not None else ""
            detail = f"<br><span style=\"color: #5C6470\">{e(i.detail)}</span>" if i.detail else ""
            parts.append(f"<li style=\"margin-bottom: 8px\">{e(i.text)}{at}{detail}</li>")
        parts.append("</ul>")
    parts.append(f"<p style=\"color: #5C6470; font-size: 13px; margin-top: 24px\">{e(memo.note)}</p></div>")
    return "".join(parts)


async def send_memo(memo: Memo, to: str, *, api_key: str, sender: str, timeout_s: float = 10.0) -> EmailResult:
    if not api_key:
        return EmailResult(ok=False, message="Email isn't set up yet (no Resend key). You can still read or print the memo here.")
    if "@" not in to or len(to) > 254:
        return EmailResult(ok=False, message="That email address doesn't look right.")
    subject = f"Tenor memo: {memo.headline}"
    key = hashlib.sha256(f"{memo.call_id}|{to.lower()}".encode()).hexdigest()[:32]
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(
                RESEND_URL,
                headers={"Authorization": f"Bearer {api_key}", "Idempotency-Key": key},
                json={"from": sender, "to": [to], "subject": subject, "html": render_html(memo), "text": render_text(memo)},
            )
    except httpx.HTTPError as e:
        record("email.send", (time.perf_counter() - started) * 1000, call_id=memo.call_id, ok=False, error=type(e).__name__)
        return EmailResult(ok=False, message="Couldn't reach the email service. You can still read or print the memo here.")
    ms = (time.perf_counter() - started) * 1000
    if response.status_code >= 400:
        detail = response.text[:200]
        record("email.send", ms, call_id=memo.call_id, ok=False, status=response.status_code, detail=detail)
        log.warning("resend refused (%s): %s", response.status_code, detail)
        return EmailResult(ok=False, message=f"The email service refused to send it ({response.status_code}). You can still read or print the memo here.")
    record("email.send", ms, call_id=memo.call_id, ok=True)
    return EmailResult(ok=True, message=f"Sent to {to}.", id=(response.json() or {}).get("id"))
