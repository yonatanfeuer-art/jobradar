#!/usr/bin/env python3
"""JobRadar: collect fresh Israel-based senior B2B sales jobs."""
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
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "data" / "companies.json"
OUTPUT_PATH = ROOT / "data" / "jobs.json"
MAX_AGE_DAYS = 7
CUTOFF = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)

TARGET_TITLES = [
    r"account executive", r"account manager", r"key account", r"strategic account",
    r"enterprise account", r"client partner", r"account director", r"client director",
    r"sales manager", r"sales director", r"head of sales", r"commercial manager",
    r"commercial director", r"business development", r"partnership", r"alliances?",
    r"partner manager", r"channel manager", r"territory manager", r"regional sales",
    r"enterprise sales", r"strategic sales", r"country manager", r"sales executive",
    r"go.?to.?market", r"market development", r"commercial lead", r"business manager",
    r"מנהל(?:ת)? לקוחות", r"מנהל(?:ת)? תיקי לקוחות", r"מנהל(?:ת)? מכירות",
    r"מנהל(?:ת)? פיתוח עסקי", r"מנהל(?:ת)? שותפויות", r"מנהל(?:ת)? שותפים",
    r"מנהל(?:ת)? ערוצים", r"לקוחות מפתח", r"לקוחות אסטרטגיים", r"סמנכ.?ל מכירות",
]
EXCLUDED_TITLES = [
    r"\bsdr\b", r"\bbdr\b", r"sales development", r"business development representative",
    r"inside sales", r"sales engineer", r"solutions? engineer", r"presales", r"pre-sales",
    r"customer success", r"customer support", r"technical support", r"technical account manager",
    r"solution architect", r"software engineer", r"developer", r"data engineer",
    r"product marketing", r"marketing manager", r"intern", r"student", r"recruit",
    r"representative", r"associate", r"entry level", r"junior", r"support",
    r"מכירות טלפוניות", r"נציג(?:ת)? מכירות", r"שירות לקוחות", r"תמיכה", r"מהנדס",
]
EXCLUDED_COMPANIES = {
    "salesforce", "palo alto networks", "confluent", "denodo", "rubrik",
    "juniper networks", "monday.com", "monday", "sentinelone", "cybereason",
    "aqua security", "wiz", "orca security", "checkpoint", "check point",
}
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
    (r"director|head of|country manager|סמנכ", 8, "Leadership"),
    (r"regional|global|territory", 7, "Regional"), (r"senior|principal", 6, "Senior"),
    (r"c-level|executive stakeholders?|cio|cto|vp", 6, "C-Level"),
    (r"complex sales|long sales cycle|multi.?stakeholder", 6, "Complex Sales"),
    (r"cloud|data|ai|software|saas|infrastructure|network|platform", 5, "Technology"),
    (r"existing accounts?|upsell|cross.?sell|expansion|farmer", 5, "Expansion"),
]
LINKEDIN_QUERIES = [
    "Enterprise Account Executive", "Account Executive", "Strategic Account Manager",
    "Key Account Manager", "Client Partner", "Business Development Manager",
    "Regional Sales Manager", "Sales Director", "Enterprise Sales", "Sales Executive",
    "Partnerships Manager", "Alliances Manager", "Channel Manager", "Country Manager",
    "Commercial Manager", "Account Director", "Head of Sales", "מנהל לקוחות",
    "מנהל מכירות", "מנהל פיתוח עסקי", "מנהל שותפויות",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def request_text(url: str, accept: str = "text/html,application/json", retries: int = 2) -> str:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; JobRadar/6.0; +https://yonatanfeuer-art.github.io/jobradar/)",
                "Accept": accept,
                "Accept-Language": "he-IL,he;q=0.9,en;q=0.8",
            })
            with urlopen(req, timeout=35) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            last = exc
            if attempt < retries:
                time.sleep(1.2 * (attempt + 1))
    assert last is not None
    raise last


def get_json(url: str) -> Any:
    return json.loads(request_text(url, "application/json"))


def clean(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def matches(patterns: list[str], text: str) -> bool:
    return any(re.search(pattern, text or "", re.I) for pattern in patterns)


def parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except ValueError:
        try:
            return parsedate_to_datetime(str(value)).astimezone(timezone.utc)
        except Exception:
            return None


def is_target_role(title: str) -> bool:
    return matches(TARGET_TITLES, title) and not matches(EXCLUDED_TITLES, title)


def is_excluded_company(company: str) -> bool:
    name = re.sub(r"[^a-z0-9. ]+", "", clean(company).lower()).strip()
    return any(name == blocked or blocked in name for blocked in EXCLUDED_COMPANIES)


def is_israel(location: str, description: str = "", title: str = "") -> bool:
    loc = clean(location)
    if matches(NON_ISRAEL_TERMS, loc) and not matches(ISRAEL_TERMS, loc):
        return False
    return matches(ISRAEL_TERMS, f"{loc} {title} {description[:1800]}")


def stable_id(source: str, company: str, external_id: str, url: str) -> str:
    raw = f"{source}|{company}|{external_id}|{url}"
    return f"{source[:2].lower()}-{hashlib.sha1(raw.encode()).hexdigest()[:18]}"


def score_job(title: str, location: str, description: str) -> tuple[int, list[str], str]:
    text = f"{title} {location} {description}".lower()
    score, tags, reasons = 38, [], []
    for pattern, boost, tag in PREFERRED_TERMS:
        if re.search(pattern, text, re.I):
            score += boost
            if tag not in tags:
                tags.append(tag)
    if re.search(r"enterprise|strategic|key account|אסטרטג", text):
        reasons.append("מכירה וניהול של לקוחות אסטרטגיים")
    if re.search(r"c-level|executive|cio|cto|vp|הנהלה", text):
        reasons.append("עבודה מול הנהלות ומקבלי החלטות")
    if re.search(r"upsell|cross.?sell|expansion|existing account|הרחבת", text):
        reasons.append("הרחבת פעילות בתוך לקוחות קיימים")
    if re.search(r"complex|multi.?stakeholder|long sales cycle|מורכב", text):
        reasons.append("עסקאות מורכבות וריבוי בעלי עניין")
    return min(99, score), tags[:5], " · ".join((reasons or ["תפקיד מכירות B2B שעשוי להתאים לניסיון שלך"])[:2])


def normalize_job(*, source: str, company: str, external_id: str, title: str, location: str,
                  description: str, posted_at: Any, url: str, allow_unknown_date: bool = False) -> dict[str, Any] | None:
    title, company = clean(title), clean(company)
    location, description, url = clean(location), clean(description), str(url or "").strip()
    if not title or not url or not is_target_role(title) or is_excluded_company(company):
        return None
    if not is_israel(location, description, title):
        return None
    dt = parse_date(posted_at)
    if dt and dt < CUTOFF:
        return None
    if not dt and not allow_unknown_date:
        return None
    dt = dt or datetime.now(timezone.utc)
    score, tags, reason = score_job(title, location, description)
    return {
        "id": stable_id(source, company, str(external_id), url),
        "company": company or "לא צוין", "title": title, "location": location or "Israel",
        "posted_at": dt.isoformat(), "url": url, "score": score, "israel": True,
        "tags": tags, "reason": reason, "source": source,
        "date_confidence": "reported" if posted_at else "discovered",
    }


def fetch_greenhouse(company: str, token: str, _: dict[str, Any]) -> list[dict[str, Any]]:
    payload = get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true")
    out = []
    for item in payload.get("jobs", []):
        job = normalize_job(source="Greenhouse", company=company, external_id=item.get("id", ""),
            title=item.get("title", ""), location=(item.get("location") or {}).get("name", ""),
            description=item.get("content", ""), posted_at=item.get("updated_at"), url=item.get("absolute_url", ""))
        if job: out.append(job)
    return out


def fetch_lever(company: str, token: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    domain = "api.eu.lever.co" if config.get("region") == "eu" else "api.lever.co"
    payload, out = get_json(f"https://{domain}/v0/postings/{token}?mode=json"), []
    for item in payload:
        categories = item.get("categories") or {}
        locations = categories.get("allLocations") or []
        location = ", ".join(locations) if locations else categories.get("location", "")
        created = item.get("createdAt")
        posted = datetime.fromtimestamp(created / 1000, tz=timezone.utc).isoformat() if isinstance(created, (int, float)) else None
        job = normalize_job(source="Lever", company=company, external_id=item.get("id", ""),
            title=item.get("text", ""), location=location,
            description=" ".join(clean(item.get(k, "")) for k in ("descriptionPlain", "additionalPlain")),
            posted_at=posted, url=item.get("hostedUrl", ""))
        if job: out.append(job)
    return out


def fetch_ashby(company: str, token: str, _: dict[str, Any]) -> list[dict[str, Any]]:
    payload, out = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}"), []
    for item in payload.get("jobs", []):
        job = normalize_job(source="Ashby", company=company, external_id=item.get("id") or item.get("jobUrl", ""),
            title=item.get("title", ""), location=item.get("location", ""),
            description=item.get("descriptionHtml") or item.get("descriptionPlain") or "",
            posted_at=item.get("publishedAt") or item.get("updatedAt"), url=item.get("jobUrl") or item.get("applyUrl", ""))
        if job: out.append(job)
    return out


def fetch_smartrecruiters(company: str, token: str, _: dict[str, Any]) -> list[dict[str, Any]]:
    payload, out = get_json(f"https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=100"), []
    for item in payload.get("content", []):
        loc = item.get("location") or {}
        location = ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")]))
        job = normalize_job(source="SmartRecruiters", company=company, external_id=item.get("id", ""),
            title=item.get("name", ""), location=location, description=item.get("department", ""),
            posted_at=item.get("releasedDate"), url=f"https://jobs.smartrecruiters.com/{token}/{item.get('id','')}")
        if job: out.append(job)
    return out


class LinkedInCardsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.cards: list[dict[str, str]] = []
        self.card: dict[str, str] | None = None
        self.field: str | None = None
        self.depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {k: v or "" for k, v in attrs}
        cls = data.get("class", "")
        if tag == "li" and "jobs-search-results__list-item" in cls:
            self.card, self.depth = {}, 1
            return
        if self.card is None:
            return
        self.depth += 1
        if tag == "a" and "base-card__full-link" in cls:
            self.card["url"] = data.get("href", "").split("?")[0]
        elif tag in {"h3", "span"} and "base-search-card__title" in cls:
            self.field = "title"
        elif tag in {"h4", "a"} and "base-search-card__subtitle" in cls:
            self.field = "company"
        elif tag == "span" and "job-search-card__location" in cls:
            self.field = "location"
        elif tag == "time":
            self.card["posted"] = data.get("datetime", "")

    def handle_endtag(self, tag: str) -> None:
        if self.card is None:
            return
        if self.field and tag in {"h3", "h4", "span", "a"}:
            self.field = None
        self.depth -= 1
        if self.depth == 0:
            if self.card.get("url") and self.card.get("title"):
                self.cards.append(self.card)
            self.card = None

    def handle_data(self, data: str) -> None:
        if self.card is not None and self.field:
            self.card[self.field] = clean(f"{self.card.get(self.field, '')} {data}")


def fetch_linkedin_query(query: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    candidates, errors = 0, 0
    for start in (0, 25, 50, 75):
        url = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
               f"keywords={quote_plus(query)}&location={quote_plus('Israel')}&f_TPR=r604800&start={start}")
        try:
            parser = LinkedInCardsParser()
            parser.feed(request_text(url))
            if not parser.cards:
                break
            candidates += len(parser.cards)
            for item in parser.cards:
                job = normalize_job(source="LinkedIn", company=item.get("company", ""),
                    external_id=item.get("url", ""), title=item.get("title", ""),
                    location=item.get("location", "Israel"), description="",
                    posted_at=item.get("posted"), url=item.get("url", ""), allow_unknown_date=True)
                if job: jobs.append(job)
        except Exception as exc:
            errors += 1
            print(f"WARNING LinkedIn {query}: {type(exc).__name__}: {exc}", file=sys.stderr)
            break
    return jobs, {"company": query, "source": "linkedin-guest", "ok": errors == 0,
                  "matches": len(jobs), "candidates": candidates, "errors": errors}


def fetch_linkedin() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    jobs, status = [], []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(fetch_linkedin_query, query) for query in LINKEDIN_QUERIES]
        for future in as_completed(futures):
            found, item_status = future.result()
            jobs.extend(found)
            status.append(item_status)
    return jobs, status


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby,
            "smartrecruiters": fetch_smartrecruiters}


def fetch_company(company: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    name, ats, token = company["name"], company["ats"], company["token"]
    fetcher = FETCHERS.get(ats)
    if not fetcher:
        return [], {"company": name, "source": ats, "ok": False, "error": "unsupported ATS"}
    try:
        found = fetcher(name, token, company)
        return found, {"company": name, "source": ats, "ok": True, "matches": len(found)}
    except Exception as exc:
        return [], {"company": name, "source": ats, "ok": False,
                    "error": f"{type(exc).__name__}: {exc}"[:220]}


def main() -> int:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    all_jobs: list[dict[str, Any]] = []
    source_status: list[dict[str, Any]] = []
    companies = [c for c in config.get("companies", []) if c.get("enabled", True)]

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(fetch_company, company) for company in companies]
        for future in as_completed(futures):
            found, status = future.result()
            all_jobs.extend(found)
            source_status.append(status)

    linkedin_jobs, linkedin_status = fetch_linkedin()
    all_jobs.extend(linkedin_jobs)
    source_status.extend(linkedin_status)

    dedup: dict[str, dict[str, Any]] = {}
    for job in all_jobs:
        key = re.sub(r"\W+", "", f"{job['company']}|{job['title']}|{job['location']}".lower())
        current = dedup.get(key)
        if not current or (job["score"], job["posted_at"]) > (current["score"], current["posted_at"]):
            dedup[key] = job
    jobs = sorted(dedup.values(), key=lambda j: (j.get("posted_at", ""), j.get("score", 0)), reverse=True)
    company_count = len({j["company"] for j in jobs})
    productive = sum(1 for s in source_status if s.get("matches", 0) > 0)
    payload = {
        "generated_at": now_iso(), "jobs": jobs, "source_status": source_status,
        "summary": {"jobs": len(jobs), "companies": company_count,
                    "sources_ok": sum(1 for s in source_status if s.get("ok")),
                    "sources_failed": sum(1 for s in source_status if not s.get("ok")),
                    "productive_sources": productive, "window_days": MAX_AGE_DAYS},
    }
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(jobs)} jobs across {company_count} companies from the last {MAX_AGE_DAYS} days")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
