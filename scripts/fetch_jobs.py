#!/usr/bin/env python3
"""JobRadar ingestion engine.

Fetches public jobs from Greenhouse, Lever and Ashby, filters them for
Yonatan's target roles in Israel, scores each role and writes data/jobs.json.
The script intentionally fails per source rather than aborting the full run.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "data" / "companies.json"
OUTPUT_PATH = ROOT / "data" / "jobs.json"

TARGET_TITLES = [
    r"account executive",
    r"enterprise account",
    r"strategic account",
    r"key account",
    r"account manager",
    r"client partner",
    r"client director",
    r"sales executive",
    r"sales manager",
    r"sales director",
    r"business development",
    r"commercial director",
    r"commercial manager",
    r"partnerships?",
    r"alliances?",
    r"channel manager",
    r"country manager",
    r"regional sales",
]

EXCLUDED_TITLES = [
    r"\bsdr\b",
    r"\bbdr\b",
    r"sales development",
    r"business development representative",
    r"inside sales",
    r"sales engineer",
    r"solutions? engineer",
    r"presales",
    r"pre-sales",
    r"customer success",
    r"customer support",
    r"technical support",
    r"intern",
    r"student",
    r"recruit",
]

ISRAEL_TERMS = [
    r"\bisrael\b",
    r"tel[ -]?aviv",
    r"herzliya",
    r"ra['’]?anana",
    r"petah[ -]?tikva",
    r"ramat[ -]?gan",
    r"bnei[ -]?brak",
    r"kfar[ -]?saba",
    r"hod[ -]?hasharon",
    r"netanya",
    r"haifa",
    r"yokneam",
    r"jerusalem",
    r"caesarea",
    r"rehevot|rehovot",
    r"\bremote.*israel\b",
    r"ישראל",
    r"תל אביב",
    r"הרצליה",
]

PREFERRED_TERMS = [
    (r"enterprise", 16, "Enterprise"),
    (r"strategic", 14, "Strategic Accounts"),
    (r"account executive", 14, "Account Executive"),
    (r"client partner", 13, "Client Partner"),
    (r"key account", 12, "Key Accounts"),
    (r"account manager", 10, "Account Management"),
    (r"business development", 10, "Business Development"),
    (r"partnership|alliance|channel", 9, "Partnerships"),
    (r"director|head of", 8, "Leadership"),
    (r"regional|territory", 7, "Regional"),
    (r"senior|principal", 6, "Senior"),
    (r"c-level|executive stakeholders?|vp|cio|cto", 6, "C-Level"),
    (r"complex sales|long sales cycle|multi.?stakeholder", 6, "Complex Sales"),
    (r"cloud|data|ai|software|saas|infrastructure|network", 5, "Technology"),
    (r"existing accounts?|upsell|cross.?sell|expansion", 5, "Expansion"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_json(url: str) -> Any:
    req = Request(
        url,
        headers={
            "User-Agent": "JobRadar/2.0 (+https://yonatanfeuer-art.github.io/jobradar/)",
            "Accept": "application/json",
        },
    )
    with urlopen(req, timeout=35) as response:
        return json.load(response)


def clean(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def matches(patterns: list[str], text: str) -> bool:
    return any(re.search(pattern, text or "", re.IGNORECASE) for pattern in patterns)


def is_target_role(title: str) -> bool:
    return matches(TARGET_TITLES, title) and not matches(EXCLUDED_TITLES, title)


def is_israel(location: str, description: str = "") -> bool:
    return matches(ISRAEL_TERMS, f"{location} {description[:1500]}")


def stable_id(source: str, company: str, external_id: str, url: str) -> str:
    raw = f"{source}|{company}|{external_id}|{url}"
    return f"{source[:2]}-{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:18]}"


def score_job(title: str, location: str, description: str) -> tuple[int, list[str], str]:
    text = f"{title} {location} {description}".lower()
    score = 44
    tags: list[str] = []
    reasons: list[str] = []

    for pattern, boost, tag in PREFERRED_TERMS:
        if re.search(pattern, text, re.IGNORECASE):
            score += boost
            if tag not in tags:
                tags.append(tag)

    if re.search(r"enterprise|strategic|key account", text):
        reasons.append("ניהול ומכירת Enterprise ללקוחות אסטרטגיים")
    if re.search(r"c-level|executive|cio|cto|vp", text):
        reasons.append("עבודה מול הנהלות ומקבלי החלטות")
    if re.search(r"upsell|cross.?sell|expansion|existing account", text):
        reasons.append("הרחבת פעילות בתוך לקוחות קיימים")
    if re.search(r"complex|multi.?stakeholder|long sales cycle", text):
        reasons.append("עסקאות מורכבות וריבוי בעלי עניין")
    if not reasons:
        reasons.append("תפקיד מכירות B2B התואם למילות החיפוש שלך")

    return min(99, score), tags[:5], " · ".join(reasons[:2])


def normalize_job(
    *,
    source: str,
    company: str,
    external_id: str,
    title: str,
    location: str,
    description: str,
    posted_at: str | None,
    url: str,
) -> dict[str, Any] | None:
    title = clean(title)
    location = clean(location)
    description = clean(description)
    url = str(url or "").strip()

    if not title or not url or not is_target_role(title):
        return None
    if not is_israel(location, description):
        return None

    score, tags, reason = score_job(title, location, description)
    return {
        "id": stable_id(source, company, str(external_id), url),
        "company": company,
        "title": title,
        "location": location or "Israel",
        "posted_at": posted_at or now_iso(),
        "url": url,
        "score": score,
        "israel": True,
        "tags": tags,
        "reason": reason,
        "source": source,
    }


def fetch_greenhouse(company: str, token: str, _: dict[str, Any]) -> list[dict[str, Any]]:
    payload = get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true")
    jobs = []
    for item in payload.get("jobs", []):
        job = normalize_job(
            source="greenhouse",
            company=company,
            external_id=str(item.get("id", "")),
            title=item.get("title", ""),
            location=(item.get("location") or {}).get("name", ""),
            description=item.get("content", ""),
            posted_at=item.get("updated_at"),
            url=item.get("absolute_url", ""),
        )
        if job:
            jobs.append(job)
    return jobs


def fetch_lever(company: str, token: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    domain = "api.eu.lever.co" if config.get("region") == "eu" else "api.lever.co"
    payload = get_json(f"https://{domain}/v0/postings/{token}?mode=json")
    jobs = []
    for item in payload:
        categories = item.get("categories") or {}
        locations = categories.get("allLocations") or []
        location = ", ".join(locations) if locations else categories.get("location", "")
        description = " ".join(
            clean(item.get(key, ""))
            for key in ("descriptionPlain", "description", "additionalPlain", "additional")
        )
        created = item.get("createdAt")
        posted_at = None
        if isinstance(created, (int, float)):
            posted_at = datetime.fromtimestamp(created / 1000, tz=timezone.utc).isoformat()
        job = normalize_job(
            source="lever",
            company=company,
            external_id=str(item.get("id", "")),
            title=item.get("text", ""),
            location=location,
            description=description,
            posted_at=posted_at,
            url=item.get("hostedUrl", ""),
        )
        if job:
            jobs.append(job)
    return jobs


def fetch_ashby(company: str, token: str, _: dict[str, Any]) -> list[dict[str, Any]]:
    payload = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}")
    jobs = []
    for item in payload.get("jobs", []):
        location = item.get("location", "")
        if item.get("isRemote") and "remote" not in location.lower():
            location = f"{location} · Remote".strip(" ·")
        job = normalize_job(
            source="ashby",
            company=company,
            external_id=str(item.get("id") or item.get("jobUrl") or ""),
            title=item.get("title", ""),
            location=location,
            description=item.get("descriptionHtml") or item.get("descriptionPlain") or "",
            posted_at=item.get("publishedAt") or item.get("updatedAt"),
            url=item.get("jobUrl") or item.get("applyUrl") or "",
        )
        if job:
            jobs.append(job)
    return jobs


FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
}


def main() -> int:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    all_jobs: list[dict[str, Any]] = []
    source_status: list[dict[str, Any]] = []

    for company in config.get("companies", []):
        if not company.get("enabled", True):
            continue

        name = company["name"]
        ats = company["ats"]
        token = company["token"]
        fetcher = FETCHERS.get(ats)
        if not fetcher:
            source_status.append({"company": name, "source": ats, "ok": False, "error": "unsupported ATS"})
            continue

        try:
            jobs = fetcher(name, token, company)
            all_jobs.extend(jobs)
            source_status.append({"company": name, "source": ats, "ok": True, "matches": len(jobs)})
            print(f"{name:<24} {ats:<10} {len(jobs):>3} matching jobs")
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError) as exc:
            message = f"{type(exc).__name__}: {exc}"
            source_status.append({"company": name, "source": ats, "ok": False, "error": message[:220]})
            print(f"WARNING {name} ({ats}): {message}", file=sys.stderr)
        except Exception as exc:  # keep one broken board from killing the whole update
            message = f"{type(exc).__name__}: {exc}"
            source_status.append({"company": name, "source": ats, "ok": False, "error": message[:220]})
            print(f"WARNING {name} ({ats}): {message}", file=sys.stderr)

    deduplicated: dict[str, dict[str, Any]] = {}
    for job in all_jobs:
        dedupe_key = f"{job['company'].lower()}|{job['title'].lower()}|{job['location'].lower()}"
        current = deduplicated.get(dedupe_key)
        if not current or job["score"] > current["score"]:
            deduplicated[dedupe_key] = job

    jobs = sorted(
        deduplicated.values(),
        key=lambda job: (job.get("score", 0), job.get("posted_at") or ""),
        reverse=True,
    )

    payload = {
        "generated_at": now_iso(),
        "jobs": jobs,
        "source_status": source_status,
        "summary": {
            "jobs": len(jobs),
            "sources_ok": sum(1 for item in source_status if item.get("ok")),
            "sources_failed": sum(1 for item in source_status if not item.get("ok")),
        },
    }
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(jobs)} real matching jobs to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
