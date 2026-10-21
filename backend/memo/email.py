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


# The app's dark theme (frontend/src/styles/tokens.css), inlined: email clients drop <style>
# blocks and web fonts, so it's tables, inline styles and system-font fallbacks.
BG, SURFACE, LINE = "#0E0B1F", "#17132F", "#2C2650"
INK, MUTED, ACCENT_INK = "#F3F1FA", "#A9A3C2", "#A08BFF"
TONE = {"neutral": LINE, "ok": "#62CC95", "warn": "#F2AC45", "danger": "#FF7B71"}
RISK = {"low": ("Low", "#62CC95"), "medium": ("Medium", "#F2AC45"), "high": ("High", "#FF7B71"), "critical": ("Critical", "#FF7B71")}
DISPLAY = "'Plus Jakarta Sans', -apple-system, 'Segoe UI', Arial, sans-serif"
BODY = "'Nunito Sans', -apple-system, 'Segoe UI', Arial, sans-serif"
MONO = "'IBM Plex Mono', ui-monospace, Menlo, Consolas, monospace"


def _risk_pill(memo: Memo) -> str:
    if memo.risk_level is None:
        return f'<span style="color:{MUTED};font-size:13px">Risk · not scored</span>'
    label, color = RISK[memo.risk_level]
    return (
        f'<span style="display:inline-block;padding:4px 12px;border:1px solid {color};border-radius:999px;'
        f'color:{color};font-size:13px;font-weight:700">Risk <span style="font-family:{MONO}">{memo.risk_score}</span> · {label}</span>'
    )


def _item(i, e) -> str:
    at = (
        f' <span style="font-family:{MONO};font-size:12px;color:{ACCENT_INK};white-space:nowrap">at {clock(i.t)}</span>'
        if i.t is not None else ""
    )
    detail = f'<div style="color:{MUTED};font-size:14px;margin-top:2px">{e(i.detail)}</div>' if i.detail else ""
    source = f'<div style="color:{MUTED};font-size:12px;margin-top:2px">{e(i.source)}</div>' if i.source else ""
    return (
        f'<tr><td style="border-left:3px solid {TONE.get(i.tone, LINE)};padding:4px 0 4px 12px">'
        f'<div style="color:{INK};font-size:15px">{e(i.text)}{at}</div>{detail}{source}</td></tr>'
        '<tr><td style="height:10px;line-height:10px;font-size:0">&nbsp;</td></tr>'
    )


def render_html(memo: Memo) -> str:
    e = html.escape
    meta = f"{memo.started_at:%d %b %Y, %H:%M} UTC · {clock(memo.duration_s)} · {'Replay' if memo.source == 'replay' else 'Microphone'}"
    parts = [
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="color-scheme" content="dark"><meta name="supported-color-schemes" content="dark"></head>',
        f'<body style="margin:0;padding:0;background:{BG}">',
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{BG}" style="background:{BG}">'
        '<tr><td align="center" style="padding:28px 12px">',
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:620px;font-family:{BODY};line-height:1.5;color:{INK}">',
        # Wordmark and header
        f'<tr><td style="padding:0 4px 18px"><span style="font-family:{DISPLAY};font-size:13px;font-weight:800;letter-spacing:2px;color:{ACCENT_INK}">TENOR</span>'
        f'<span style="font-size:13px;color:{MUTED}"> · Your call memo</span></td></tr>',
        f'<tr><td style="padding:0 4px"><div style="color:{MUTED};font-size:13px;margin-bottom:10px">{e(meta)}</div>{_risk_pill(memo)}'
        f'<h1 style="font-family:{DISPLAY};font-size:26px;line-height:1.25;color:{INK};margin:16px 0 10px">{e(memo.headline)}</h1>'
        f'<p style="font-size:17px;color:{INK};margin:0 0 22px">{e(memo.summary)}</p></td></tr>',
    ]
    for s in memo.sections:
        body = (
            f'<p style="color:{MUTED};margin:0;font-size:15px">{e(s.empty)}</p>' if not s.items
            else '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">' + "".join(_item(i, e) for i in s.items) + "</table>"
        )
        parts.append(
            f'<tr><td bgcolor="{SURFACE}" style="background:{SURFACE};border:1px solid {LINE};border-radius:14px;padding:18px 20px">'
            f'<h2 style="font-family:{DISPLAY};font-size:16px;color:{INK};margin:0 0 12px">{e(s.title)}</h2>{body}</td></tr>'
            '<tr><td style="height:14px;line-height:14px;font-size:0">&nbsp;</td></tr>'
        )
    parts.append(f'<tr><td style="padding:8px 4px 0;color:{MUTED};font-size:13px">{e(memo.note)}</td></tr>')
    parts.append("</table></td></tr></table></body></html>")
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
