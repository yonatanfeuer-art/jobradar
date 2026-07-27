#!/usr/bin/env python3
"""Collect fresh, Israel-based senior enterprise sales jobs.

The crawler only publishes real job URLs, preserves first-seen history, rejects
excluded/cyber roles, and keeps the previous healthy dataset if a run collapses.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "data" / "companies.json"
OUTPUT_PATH = ROOT / "data" / "jobs.json"
MAX_AGE_DAYS = 14
CUTOFF = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)

TARGET_TITLES = [
    r"enterprise (?:account executive|sales)", r"account executive", r"sales executive",
    r"strategic account", r"key account", r"client partner", r"account director",
    r"business development manager", r"regional sales manager", r"sales director",
    r"head of sales", r"partnerships? manager", r"alliances? manager", r"channel manager",
    r"country manager", r"commercial director", r"commercial manager",
    r"מנהל(?:ת)? לקוחות", r"מנהל(?:ת)? מכירות", r"מנהל(?:ת)? פיתוח עסקי",
    r"מנהל(?:ת)? שותפויות", r"לקוחות אסטרטגיים", r"לקוחות מפתח",
]
EXCLUDED_TITLES = [
    r"\bsdr\b", r"\bbdr\b", r"sales development", r"business development representative",
    r"inside sales", r"sales engineer", r"solutions? engineer", r"presales", r"pre-sales",
    r"customer success", r"customer support", r"technical support", r"technical account manager",
    r"solution architect", r"software engineer", r"developer", r"data engineer", r"product marketing",
    r"representative", r"associate", r"entry.?level", r"junior", r"intern", r"student", r"support",
    r"cyber", r"security sales", r"security account", r"מכירות טלפוניות", r"נציג(?:ת)? מכירות",
    r"שירות לקוחות", r"תמיכה", r"מהנדס",
]
EXCLUDED_COMPANIES = {
    "salesforce", "palo alto networks", "confluent", "denodo", "rubrik", "juniper networks",
    "monday.com", "monday", "sentinelone", "cybereason", "aqua security", "wiz", "orca security",
    "checkpoint", "check point",
}
ISRAEL_TERMS = [
    r"\bisrael\b", r"tel[ -]?aviv", r"herzliya", r"ra['’]?anana", r"petah[ -]?tikva",
    r"ramat[ -]?gan", r"bnei[ -]?brak", r"kfar[ -]?saba", r"hod[ -]?hasharon", r"netanya",
    r"haifa", r"yokneam", r"jerusalem", r"caesarea", r"rehovot", r"beer[ -]?sheva",
    r"rishon", r"holon", r"modi.?in", r"remote.*israel", r"ישראל", r"תל אביב", r"הרצליה",
    r"רעננה", r"פתח תקווה", r"רמת גן", r"בני ברק", r"כפר סבא", r"הוד השרון", r"נתניה",
    r"חיפה", r"יקנעם", r"ירושלים", r"קיסריה", r"רחובות", r"באר שבע", r"ראשון לציון", r"חולון",
]
NON_ISRAEL_TERMS = [r"\blondon\b", r"\bnew york\b", r"\bgermany\b", r"\bfrance\b", r"\bspain\b",
                    r"\bitaly\b", r"\bsingapore\b", r"\bindia\b", r"\baustralia\b", r"\bcanada\b"]
PREFERRED_TERMS = [
    (r"enterprise", 20, "Enterprise"), (r"strategic", 16, "Strategic Accounts"),
    (r"account executive", 15, "Account Executive"), (r"client partner", 14, "Client Partner"),
    (r"key account", 13, "Key Accounts"), (r"business development", 11, "Business Development"),
    (r"partnership|alliance|channel", 10, "Partnerships"), (r"director|head of|country manager", 9, "Leadership"),
    (r"regional|global|territory", 7, "Regional"), (r"c-level|cio|cto|executive stakeholder", 7, "C-Level"),
    (r"complex sales|long sales cycle|multi.?stakeholder", 7, "Complex Sales"),
    (r"cloud|data|\bai\b|software|saas|infrastructure|network|platform", 6, "Technology"),
]
LINKEDIN_QUERIES = [
    "Enterprise Account Executive", "Account Executive", "Strategic Account Manager", "Key Account Manager",
    "Client Partner", "Business Development Manager", "Regional Sales Manager", "Sales Director",
    "Enterprise Sales", "Sales Executive", "Partnerships Manager", "Alliances Manager", "Channel Manager",
    "Account Director", "Head of Sales", "מנהל לקוחות", "מנהל מכירות", "מנהל פיתוח עסקי", "מנהל שותפויות",
]
ALLOWED_JOB_HOSTS = ("linkedin.com", "greenhouse.io", "lever.co", "ashbyhq.com", "smartrecruiters.com",
                     "workdayjobs.com", "comeet.com", "workable.com", "teamtailor.com")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def request_text(url: str, accept: str = "text/html,application/json", retries: int = 2) -> str:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
                "Accept": accept, "Accept-Language": "en-US,en;q=0.9,he;q=0.8",
            })
            with urlopen(req, timeout=30) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            last = exc
            if attempt < retries:
                time.sleep(1.0 + attempt)
    raise last or RuntimeError("request failed")


def get_json(url: str) -> Any:
    return json.loads(request_text(url, "application/json"))


def clean(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except ValueError:
        try:
            return parsedate_to_datetime(text).astimezone(timezone.utc)
        except Exception:
            return None


def matches(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text or "", re.I) for p in patterns)


def is_target_role(title: str) -> bool:
    return matches(TARGET_TITLES, title) and not matches(EXCLUDED_TITLES, title)


def is_excluded_company(company: str) -> bool:
    name = re.sub(r"[^a-z0-9. ]+", "", clean(company).lower()).strip()
    return any(name == blocked or blocked in name for blocked in EXCLUDED_COMPANIES)


def is_israel(location: str, description: str = "", title: str = "") -> bool:
    loc = clean(location)
    if matches(NON_ISRAEL_TERMS, loc) and not matches(ISRAEL_TERMS, loc):
        return False
    return matches(ISRAEL_TERMS, f"{loc} {title} {description[:1500]}")


def valid_job_url(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower().removeprefix("www.")
        return url.startswith("https://") and (any(host.endswith(h) for h in ALLOWED_JOB_HOSTS) or "/careers/" in url or "/jobs/" in url)
    except Exception:
        return False


def stable_id(source: str, company: str, external_id: str, url: str) -> str:
    raw = f"{source}|{company}|{external_id or url}".lower()
    return f"{source[:2].lower()}-{hashlib.sha1(raw.encode()).hexdigest()[:18]}"


def score_job(title: str, location: str, description: str) -> tuple[int, list[str], str]:
    text = f"{title} {location} {description}".lower()
    score, tags, reasons = 35, [], []
    for pattern, boost, tag in PREFERRED_TERMS:
        if re.search(pattern, text, re.I):
            score += boost
            if tag not in tags: tags.append(tag)
    if re.search(r"enterprise|strategic|key account|אסטרטג", text): reasons.append("מכירה וניהול של לקוחות אסטרטגיים")
    if re.search(r"c-level|executive|cio|cto|vp|הנהלה", text): reasons.append("עבודה מול הנהלות ומקבלי החלטות")
    if re.search(r"complex|multi.?stakeholder|long sales cycle|מורכב", text): reasons.append("עסקאות מורכבות וריבוי בעלי עניין")
    return min(99, score), tags[:5], " · ".join((reasons or ["תפקיד מכירות B2B בכיר שמתאים לניסיון שלך"])[:2])


def normalize_job(*, source: str, company: str, external_id: str, title: str, location: str,
                  description: str, posted_at: Any, url: str, allow_unknown_date: bool = False) -> dict[str, Any] | None:
    title, company, location, description = map(clean, (title, company, location, description))
    url = html.unescape(str(url or "")).split("?")[0].strip()
    if not title or not company or not is_target_role(title) or is_excluded_company(company) or not valid_job_url(url): return None
    if not is_israel(location, description, title): return None
    dt = parse_date(posted_at)
    if dt and dt < CUTOFF: return None
    if not dt and not allow_unknown_date: return None
    score, tags, reason = score_job(title, location, description)
    return {"id": stable_id(source, company, str(external_id), url), "company": company, "title": title,
            "location": location or "Israel", "posted_at": dt.isoformat() if dt else None, "url": url,
            "score": score, "israel": True, "tags": tags, "reason": reason, "source": source,
            "date_confidence": "reported" if dt else "discovered"}


def fetch_greenhouse(company: str, token: str, _: dict[str, Any]) -> list[dict[str, Any]]:
    payload = get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true")
    out = []
    for item in payload.get("jobs", []):
        job = normalize_job(source="Greenhouse", company=company, external_id=item.get("id", ""), title=item.get("title", ""),
            location=(item.get("location") or {}).get("name", ""), description=item.get("content", ""),
            posted_at=item.get("updated_at"), url=item.get("absolute_url", ""))
        if job: out.append(job)
    return out


def fetch_lever(company: str, token: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    domain = "api.eu.lever.co" if config.get("region") == "eu" else "api.lever.co"
    payload, out = get_json(f"https://{domain}/v0/postings/{token}?mode=json"), []
    for item in payload:
        categories = item.get("categories") or {}; locations = categories.get("allLocations") or []
        created = item.get("createdAt"); posted = datetime.fromtimestamp(created / 1000, tz=timezone.utc).isoformat() if isinstance(created, (int, float)) else None
        job = normalize_job(source="Lever", company=company, external_id=item.get("id", ""), title=item.get("text", ""),
            location=", ".join(locations) or categories.get("location", ""), description=item.get("descriptionPlain", ""),
            posted_at=posted, url=item.get("hostedUrl", ""))
        if job: out.append(job)
    return out


def fetch_ashby(company: str, token: str, _: dict[str, Any]) -> list[dict[str, Any]]:
    payload, out = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}"), []
    for item in payload.get("jobs", []):
        job = normalize_job(source="Ashby", company=company, external_id=item.get("id") or item.get("jobUrl", ""),
            title=item.get("title", ""), location=item.get("location", ""), description=item.get("descriptionHtml", ""),
            posted_at=item.get("publishedAt") or item.get("updatedAt"), url=item.get("jobUrl") or item.get("applyUrl", ""))
        if job: out.append(job)
    return out


def fetch_smartrecruiters(company: str, token: str, _: dict[str, Any]) -> list[dict[str, Any]]:
    payload, out = get_json(f"https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=100"), []
    for item in payload.get("content", []):
        loc = item.get("location") or {}; location = ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")]))
        job = normalize_job(source="SmartRecruiters", company=company, external_id=item.get("id", ""), title=item.get("name", ""),
            location=location, description=item.get("department", ""), posted_at=item.get("releasedDate"),
            url=f"https://jobs.smartrecruiters.com/{token}/{item.get('id','')}")
        if job: out.append(job)
    return out


def extract_linkedin_cards(page: str) -> list[dict[str, str]]:
    """Parse both LinkedIn guest API markup variants without depending on fragile DOM depth."""
    cards = []
    blocks = re.findall(r"<(?:li|div)[^>]+(?:base-card|jobs-search-results__list-item)[^>]*>(.*?)</(?:li|div)>", page, re.I | re.S)
    if not blocks: blocks = re.findall(r"<li[^>]*>(.*?)</li>", page, re.I | re.S)
    for block in blocks:
        href = re.search(r'href=["\']([^"\']*linkedin\.com/jobs/view/[^"\']+)', block, re.I)
        title = re.search(r'class=["\'][^"\']*base-search-card__title[^"\']*["\'][^>]*>(.*?)</', block, re.I | re.S)
        company = re.search(r'class=["\'][^"\']*base-search-card__subtitle[^"\']*["\'][^>]*>(.*?)</', block, re.I | re.S)
        location = re.search(r'class=["\'][^"\']*job-search-card__location[^"\']*["\'][^>]*>(.*?)</', block, re.I | re.S)
        posted = re.search(r'<time[^>]+datetime=["\']([^"\']+)', block, re.I)
        if href and title and company:
            cards.append({"url": html.unescape(href.group(1)).split("?")[0], "title": clean(title.group(1)),
                          "company": clean(company.group(1)), "location": clean(location.group(1) if location else "Israel"),
                          "posted": posted.group(1) if posted else ""})
    return cards


def fetch_linkedin_query(query: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    jobs, candidates, errors = [], 0, 0
    for start in (0, 25, 50):
        url = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
               f"keywords={quote_plus(query)}&location=Israel&geoId=101620260&f_TPR=r1209600&start={start}")
        try:
            cards = extract_linkedin_cards(request_text(url))
            if not cards: break
            candidates += len(cards)
            for item in cards:
                job = normalize_job(source="LinkedIn", company=item["company"], external_id=item["url"], title=item["title"],
                    location=item["location"], description="", posted_at=item["posted"], url=item["url"], allow_unknown_date=True)
                if job: jobs.append(job)
        except Exception as exc:
            errors += 1; print(f"WARNING LinkedIn {query}: {exc}", file=sys.stderr); break
    return jobs, {"company": query, "source": "linkedin-guest", "ok": errors == 0 and candidates > 0,
                  "matches": len(jobs), "candidates": candidates, "errors": errors,
                  "error": "No cards returned (blocked or markup changed)" if not candidates and not errors else None}


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby, "smartrecruiters": fetch_smartrecruiters}


def fetch_company(config: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    name, ats, token = config["name"], config["ats"], config["token"]
    try:
        found = FETCHERS[ats](name, token, config)
        return found, {"company": name, "source": ats, "ok": True, "matches": len(found)}
    except Exception as exc:
        return [], {"company": name, "source": ats, "ok": False, "error": f"{type(exc).__name__}: {exc}"[:220]}


def load_previous() -> dict[str, Any]:
    try: return json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    except Exception: return {"jobs": []}


def main() -> int:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8")); previous = load_previous()
    all_jobs, statuses = [], []
    companies = [c for c in config.get("companies", []) if c.get("enabled", True) and not is_excluded_company(c.get("name", ""))]
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(fetch_company, c) for c in companies]
        for future in as_completed(futures):
            found, status = future.result(); all_jobs.extend(found); statuses.append(status)
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(fetch_linkedin_query, q) for q in LINKEDIN_QUERIES]
        for future in as_completed(futures):
            found, status = future.result(); all_jobs.extend(found); statuses.append(status)

    previous_by_id = {j.get("id"): j for j in previous.get("jobs", []) if j.get("id")}
    dedup: dict[str, dict[str, Any]] = {}
    seen_at = now_iso()
    for job in all_jobs:
        key = re.sub(r"\W+", "", f"{job['company']}|{job['title']}|{job['location']}".lower())
        old = previous_by_id.get(job["id"], {})
        job["first_seen_at"] = old.get("first_seen_at") or old.get("posted_at") or seen_at
        job["last_seen_at"] = seen_at
        if not job.get("posted_at"): job["posted_at"] = job["first_seen_at"]
        current = dedup.get(key)
        if not current or (job["score"], job["posted_at"]) > (current["score"], current["posted_at"]): dedup[key] = job
    jobs = sorted(dedup.values(), key=lambda j: (j.get("posted_at", ""), j.get("score", 0)), reverse=True)
    ats_ok = sum(1 for s in statuses if s.get("ok") and s.get("source") != "linkedin-guest")
    linkedin_candidates = sum(s.get("candidates", 0) for s in statuses if s.get("source") == "linkedin-guest")
    previous_count = len(previous.get("jobs", []))
    healthy = len(jobs) >= 5 or previous_count < 5
    if not healthy:
        print(f"UNHEALTHY RUN: found {len(jobs)} jobs; preserving previous {previous_count}", file=sys.stderr)
        jobs = previous.get("jobs", [])
    payload = {"generated_at": now_iso(), "jobs": jobs, "source_status": statuses,
               "summary": {"jobs": len(jobs), "companies": len({j.get('company') for j in jobs}),
                           "sources_ok": sum(1 for s in statuses if s.get("ok")),
                           "sources_failed": sum(1 for s in statuses if not s.get("ok")),
                           "productive_sources": sum(1 for s in statuses if s.get("matches", 0) > 0),
                           "linkedin_candidates": linkedin_candidates, "ats_sources_ok": ats_ok,
                           "window_days": MAX_AGE_DAYS, "healthy": healthy}}
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(jobs)} jobs; LinkedIn candidates={linkedin_candidates}; healthy={healthy}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
