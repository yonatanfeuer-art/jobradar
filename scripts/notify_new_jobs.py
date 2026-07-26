#!/usr/bin/env python3
"""Send one email when at least N new jobs are found or a high-score match appears.

Required environment variables:
  ALERT_EMAIL, SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD
Optional:
  EMAIL_THRESHOLD (default 3), ALERT_SCORE (default 95), JOBRADAR_URL
"""
from __future__ import annotations

import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "data" / "jobs.json"
PREVIOUS = ROOT / "data" / "jobs.previous.json"


def load_jobs(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("jobs", [])
    except (json.JSONDecodeError, OSError):
        return []


def main() -> int:
    current = load_jobs(CURRENT)
    previous = load_jobs(PREVIOUS)
    previous_ids = {job.get("id") for job in previous}
    new_jobs = [job for job in current if job.get("id") not in previous_ids]

    threshold = int(os.getenv("EMAIL_THRESHOLD", "3"))
    alert_score = int(os.getenv("ALERT_SCORE", "95"))
    top_matches = [job for job in new_jobs if int(job.get("score") or 0) >= alert_score]

    print(f"Found {len(new_jobs)} new jobs; {len(top_matches)} high-score matches")
    if len(new_jobs) < threshold and not top_matches:
        print("No email needed")
        return 0

    required = ["ALERT_EMAIL", "SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        print("Email skipped; missing secrets: " + ", ".join(missing))
        return 0

    site_url = os.getenv("JOBRADAR_URL", "https://yonatanfeuer-art.github.io/jobradar/")
    subject = f"JobRadar: {len(new_jobs)} משרות חדשות"
    if top_matches:
        subject = f"🔥 JobRadar: {len(top_matches)} התאמות חזקות מתוך {len(new_jobs)} חדשות"

    rows = []
    for job in sorted(new_jobs, key=lambda j: int(j.get("score") or 0), reverse=True):
        rows.append(
            f'<li style="margin-bottom:14px"><strong>{job.get("company", "")}</strong> — '
            f'{job.get("title", "")} ({job.get("score", 0)}%)<br>'
            f'<span style="color:#64748b">{job.get("location", "")}</span><br>'
            f'<a href="{job.get("url", "")}">פתח את המשרה</a></li>'
        )

    html = f"""
    <div dir="rtl" style="font-family:Arial,sans-serif;max-width:680px;margin:auto">
      <h2>{subject}</h2>
      <p>נמצאו משרות חדשות מאז הסריקה הקודמת:</p>
      <ol>{''.join(rows)}</ol>
      <p><a href="{site_url}" style="background:#22c55e;color:#052e16;padding:12px 18px;border-radius:8px;text-decoration:none;font-weight:bold">פתח את JobRadar</a></p>
    </div>
    """

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = os.environ["SMTP_USERNAME"]
    message["To"] = os.environ["ALERT_EMAIL"]
    message.set_content(f"נמצאו {len(new_jobs)} משרות חדשות. {site_url}")
    message.add_alternative(html, subtype="html")

    host = os.environ["SMTP_HOST"]
    port = int(os.environ["SMTP_PORT"])
    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context) as smtp:
            smtp.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port) as smtp:
            smtp.starttls(context=context)
            smtp.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
            smtp.send_message(message)

    print("Alert email sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
