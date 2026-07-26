#!/usr/bin/env python3
"""JobRadar ingestion engine.

Collects public job postings from supported ATS boards and public web-search
results, keeps Israel-based target sales roles posted in the last seven days,
deduplicates them and writes data/jobs.json.

The public-search layer does not bypass logins, CAPTCHAs or access controls. It
only indexes links that are publicly visible to search engines, including links
from LinkedIn, AllJobs, JobMaster, Drushim and company career sites when indexed.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "data" / "companies.json"
OUTPUT_PATH = ROOT / "data" / "jobs.json"
MAX_AGE_DAYS = 7
CUTOFF = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)

TARGET_TITLES = [
    r"enterprise account executive", r"enterprise account manager",
    r"strategic account manager", r"strategic accounts?", r"global account manager",
    r"regional account manager", r"business development manager",
    r"strategic partnerships? manager", r"alliances? manager", r"partner manager",
    r"client partner", r"key account manager", r"sales director",
    r"enterprise sales", r"strategic sales", r"commercial director",
    r"commercial manager", r"account director", r"client director",
    r"מנהל(?:ת)? לקוחות אסטרטגיים", r"מנהל(?:ת)? תיקי לקוחות אסטרטגיים",
    r"מנהל(?:ת)? לקוחות אנטרפרייז", r"מנהל(?:ת)? מכירות אנטרפרייז",
    r"מנהל(?:ת)? פיתוח עסקי", r"מנהל(?:ת)? שותפויות אסטרטגיות",
    r"מנהל(?:ת)? שותפים", r"מנהל(?:ת)? ערוצים", r"מנהל(?:ת)? מכירות אזורי",
    r"מנהל(?:ת)? מכירות גלובלי", r"מנהל(?:ת)? לקוחות מפתח",
    r"סמנכ.?ל מכירות", r"מנהל(?:ת)? מכירות",
]

EXCLUDED_TITLES = [
    r"\bsdr\b", r"\bbdr\b", r"sales development", r"business development representative",
    r"inside sales", r"sales engineer", r"solutions? engineer", r"presales", r"pre-sales",
    r"customer success", r"customer support", r"technical support", r"technical account manager",
    r"product marketing", r"marketing manager", r"temporary", r"temp\b", r"maternity",
    r"intern", r"student", r"recruit", r"representative", r"associate",
    r"מכירות טלפוניות", r"נציג(?:ת)? מכירות", r"תמיכה", r"שירות לקוחות",
]

ISRAEL_TERMS = [
    r"\bisrael\b", r"tel[ -]?aviv", r"herzliya", r"ra['’]?anana", r"petah[ -]?tikva",
    r"ramat[ -]?gan", r"bnei[ -]?brak", r"kfar[ -]?saba", r"hod[ -]?hasharon",
    r"netanya", r"haifa", r"yokneam", r"jerusalem", r"caesarea", r"rehovot",
    r"beer[ -]?sheva", r"rishon", r"holon", r"modi.?in", r"remote.*israel",
    r"ישראל", r"תל אביב", r"הרצליה", r"רעננה", r"פתח תקווה", r"רמת גן",
    r"בני ברק", r"כפר סבא", r"הוד השרון", r"נתניה", r"חיפה", r"יקנעם",
    r"ירושלים", r"קיסריה", r"רחובות", r"באר שבע", r"ראשון לציון", r"חולון",
]

NON_ISRAEL_TERMS = [
    r"\bjapan\b", r"\blondon\b", r"\bnew york\b", r"\bgermany\b", r"\bfrance\b",
    r"\bspain\b", r"\bitaly\b", r"\bsingapore\b", r"\bindia\b", r"\baustralia\b",
    r"\bunited states\b", r"\busa\b", r"\bcanada\b", r"\bpoland\b", r"\bnetherlands\b",
]

PREFERRED_TERMS = [
    (r"enterprise", 18, "Enterprise"), (r"strategic", 15, "Strategic Accounts"),
    (r"account executive", 14, "Account Executive"), (r"client partner", 13, "Client Partner"),
    (r"key account", 12, "Key Accounts"), (r"account manager", 10, "Account Management"),
    (r"business development", 10, "Business Development"),
    (r"partnership|alliance|partner manager|channel", 9, "Partnerships"),
    (r"director|head of|סמנכ", 8, "Leadership"), (r"regional|global|territory", 7, "Regional"),
    (r"senior|principal", 6, "Senior"), (r"c-level|executive stakeholders?|cio|cto|vp", 6, "C-Level"),
    (r"complex sales|long sales cycle|multi.?stakeholder", 6, "Complex Sales"),
    (r"cloud|data|ai|software|saas|infrastructure|network|cyber", 5, "Technology"),
    (r"existing accounts?|upsell|cross.?sell|expansion|farmer", 5, "Expansion"),
]

SEARCH_TITLES = [
    '"Enterprise Account Executive"', '"Enterprise Account Manager"',
    '"Strategic Account Manager"', '"Global Account Manager"',
    '"Regional Account Manager"', '"Business Development Manager"',
    '"Strategic Partnerships Manager"', '"Alliances Manager"',
    '"Partner Manager"', '"Client Partner"', '"Key Account Manager"',
    '"Sales Director"', '"מנהל לקוחות אסטרטגיים"', '"מנהל פיתוח עסקי"',
    '"מנהל שותפויות"', '"מנהל לקוחות מפתח"', '"מנהל מכירות אנטרפרייז"',
]

SEARCH_SITES = [
    ("LinkedIn", "site:linkedin.com/jobs/view"),
    ("AllJobs", "site:alljobs.co.il"),
    ("JobMaster", "site:jobmaster.co.il"),
    ("Drushim", "site:drushim.co.il"),
    ("Career site", "(careers OR jobs OR greenhouse OR lever OR ashby OR workdayjobs OR smartrecruiters)"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def request_text(url: str, accept: str = "text/html,application/xhtml+xml,application/json") -> str:
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; JobRadar/3.0; +https://yonatanfeuer-art.github.io/jobradar/)",
        "Accept": accept,
        "Accept-Language": "he-IL,he;q=0.9,en;q=0.8",
    })
    with urlopen(req, timeout=35) as response:
        return response.read().decode("utf-8", errors="replace")


def get_json(url: str) -> Any:
    return json.loads(request_text(url, "application/json"))


def clean(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def matches(patterns: list[str], text: str) -> bool:
    return any(re.search(pattern, text or "", re.IGNORECASE) for pattern in patterns)


def parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        try:
            return parsedate_to_datetime(str(value)).astimezone(timezone.utc)
        except Exception:
            return None


def is_recent(posted_at: Any) -> bool:
    dt = parse_date(posted_at)
    return bool(dt and dt >= CUTOFF)


def is_target_role(title: str) -> bool:
    return matches(TARGET_TITLES, title) and not matches(EXCLUDED_TITLES, title)


def is_israel(location: str, description: str = "", title: str = "") -> bool:
    location_text = clean(location)
    if matches(NON_ISRAEL_TERMS, location_text) and not matches(ISRAEL_TERMS, location_text):
        return False
    return matches(ISRAEL_TERMS, f"{location_text} {title} {description[:1200]}")


def stable_id(source: str, company: str, external_id: str, url: str) -> str:
    raw = f"{source}|{company}|{external_id}|{url}"
    return f"{source[:2]}-{hashlib.sha1(raw.encode()).hexdigest()[:18]}"


def score_job(title: str, location: str, description: str) -> tuple[int, list[str], str]:
    text = f"{title} {location} {description}".lower()
    score, tags, reasons = 42, [], []
    for pattern, boost, tag in PREFERRED_TERMS:
        if re.search(pattern, text, re.IGNORECASE):
            score += boost
            if tag not in tags:
                tags.append(tag)
    if re.search(r"enterprise|strategic|key account|אסטרטג", text):
        reasons.append("ניהול ומכירת Enterprise ללקוחות אסטרטגיים")
    if re.search(r"c-level|executive|cio|cto|vp|הנהלה", text):
        reasons.append("עבודה מול הנהלות ומקבלי החלטות")
    if re.search(r"upsell|cross.?sell|expansion|existing account|הרחבת", text):
        reasons.append("הרחבת פעילות בתוך לקוחות קיימים")
    if re.search(r"complex|multi.?stakeholder|long sales cycle|מורכב", text):
        reasons.append("עסקאות מורכבות וריבוי בעלי עניין")
    return min(99, score), tags[:5], " · ".join((reasons or ["תפקיד מכירות B2B התואם לחיפוש שלך"])[:2])


def normalize_job(*, source: str, company: str, external_id: str, title: str, location: str,
                  description: str, posted_at: Any, url: str) -> dict[str, Any] | None:
    title, location, description, url = clean(title), clean(location), clean(description), str(url or "").strip()
    if not title or not url or not is_target_role(title):
        return None
    if not is_israel(location, description, title):
        return None
    if not is_recent(posted_at):
        return None
    dt = parse_date(posted_at)
    score, tags, reason = score_job(title, location, description)
    return {
        "id": stable_id(source, company, str(external_id), url), "company": company or "לא צוין",
        "title": title, "location": location or "Israel", "posted_at": dt.isoformat() if dt else now_iso(),
        "url": url, "score": score, "israel": True, "tags": tags, "reason": reason, "source": source,
    }


def fetch_greenhouse(company: str, token: str, _: dict[str, Any]) -> list[dict[str, Any]]:
    payload = get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true")
    output = []
    for item in payload.get("jobs", []):
        job = normalize_job(source="greenhouse", company=company, external_id=item.get("id", ""),
            title=item.get("title", ""), location=(item.get("location") or {}).get("name", ""),
            description=item.get("content", ""), posted_at=item.get("updated_at"), url=item.get("absolute_url", ""))
        if job: output.append(job)
    return output


def fetch_lever(company: str, token: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    domain = "api.eu.lever.co" if config.get("region") == "eu" else "api.lever.co"
    payload, output = get_json(f"https://{domain}/v0/postings/{token}?mode=json"), []
    for item in payload:
        categories = item.get("categories") or {}
        locations = categories.get("allLocations") or []
        location = ", ".join(locations) if locations else categories.get("location", "")
        created = item.get("createdAt")
        posted = datetime.fromtimestamp(created / 1000, tz=timezone.utc).isoformat() if isinstance(created, (int, float)) else None
        job = normalize_job(source="lever", company=company, external_id=item.get("id", ""),
            title=item.get("text", ""), location=location,
            description=" ".join(clean(item.get(k, "")) for k in ("descriptionPlain", "additionalPlain")),
            posted_at=posted, url=item.get("hostedUrl", ""))
        if job: output.append(job)
    return output


def fetch_ashby(company: str, token: str, _: dict[str, Any]) -> list[dict[str, Any]]:
    payload, output = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}"), []
    for item in payload.get("jobs", []):
        location = item.get("location", "")
        job = normalize_job(source="ashby", company=company, external_id=item.get("id") or item.get("jobUrl", ""),
            title=item.get("title", ""), location=location,
            description=item.get("descriptionHtml") or item.get("descriptionPlain") or "",
            posted_at=item.get("publishedAt") or item.get("updatedAt"), url=item.get("jobUrl") or item.get("applyUrl", ""))
        if job: output.append(job)
    return output


def rss_items(query: str) -> list[dict[str, str]]:
    url = f"https://www.bing.com/search?format=rss&setlang=he&q={quote_plus(query)}"
    root = ET.fromstring(request_text(url, "application/rss+xml,text/xml"))
    items = []
    for item in root.findall("./channel/item"):
        items.append({child.tag: (child.text or "") for child in item})
    return items


def source_name(url: str, fallback: str) -> str:
    host = urlparse(url).netloc.lower()
    if "linkedin.com" in host: return "LinkedIn"
    if "alljobs.co.il" in host: return "AllJobs"
    if "jobmaster.co.il" in host: return "JobMaster"
    if "drushim.co.il" in host: return "Drushim"
    return fallback


def infer_company(title: str, description: str, url: str) -> str:
    for sep in [" - ", " | ", " at ", " ב-"]:
        parts = title.split(sep)
        if len(parts) > 1:
            candidate = clean(parts[-1])
            if 1 < len(candidate) < 70 and not matches(TARGET_TITLES, candidate):
                return candidate
    host = urlparse(url).netloc.replace("www.", "")
    return host.split(".")[0].title() if host else "לא צוין"


def fetch_public_search() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    jobs, status, seen_urls = [], [], set()
    for label, site_query in SEARCH_SITES:
        matches_count, errors = 0, 0
        for title_query in SEARCH_TITLES:
            query = f"{title_query} (Israel OR ישראל OR 'Tel Aviv' OR תל אביב) {site_query}"
            try:
                for item in rss_items(query):
                    url, title = clean(item.get("link")), clean(item.get("title"))
                    description, posted = clean(item.get("description")), item.get("pubDate")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    company = infer_company(title, description, url)
                    job = normalize_job(source=source_name(url, label), company=company,
                        external_id=url, title=title, location=f"Israel · {label}",
                        description=description, posted_at=posted, url=url)
                    if job:
                        jobs.append(job); matches_count += 1
            except Exception as exc:
                errors += 1
                print(f"WARNING web search {label}: {type(exc).__name__}: {exc}", file=sys.stderr)
        status.append({"company": label, "source": "public-search", "ok": errors < len(SEARCH_TITLES),
                       "matches": matches_count, "errors": errors})
    return jobs, status


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby}


def main() -> int:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    all_jobs, source_status = [], []
    for company in config.get("companies", []):
        if not company.get("enabled", True): continue
        name, ats, token = company["name"], company["ats"], company["token"]
        fetcher = FETCHERS.get(ats)
        if not fetcher:
            source_status.append({"company": name, "source": ats, "ok": False, "error": "unsupported ATS"}); continue
        try:
            jobs = fetcher(name, token, company)
            all_jobs.extend(jobs)
            source_status.append({"company": name, "source": ats, "ok": True, "matches": len(jobs)})
            print(f"{name:<24} {ats:<10} {len(jobs):>3} matching jobs")
        except Exception as exc:
            source_status.append({"company": name, "source": ats, "ok": False,
                                  "error": f"{type(exc).__name__}: {exc}"[:220]})
            print(f"WARNING {name} ({ats}): {type(exc).__name__}: {exc}", file=sys.stderr)

    web_jobs, web_status = fetch_public_search()
    all_jobs.extend(web_jobs); source_status.extend(web_status)

    deduplicated: dict[str, dict[str, Any]] = {}
    for job in all_jobs:
        key = re.sub(r"\W+", "", f"{job['company']}|{job['title']}|{job['location']}".lower())
        current = deduplicated.get(key)
        if not current or (job["score"], job["posted_at"]) > (current["score"], current["posted_at"]):
            deduplicated[key] = job
    jobs = sorted(deduplicated.values(), key=lambda j: (j.get("posted_at", ""), j.get("score", 0)), reverse=True)
    payload = {
        "generated_at": now_iso(), "jobs": jobs, "source_status": source_status,
        "summary": {"jobs": len(jobs), "sources_ok": sum(1 for s in source_status if s.get("ok")),
                    "sources_failed": sum(1 for s in source_status if not s.get("ok")),
                    "window_days": MAX_AGE_DAYS},
    }
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(jobs)} jobs from the last {MAX_AGE_DAYS} days")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
