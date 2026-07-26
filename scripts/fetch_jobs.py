#!/usr/bin/env python3
"""Collect public Israel sales jobs from the last seven days."""
from __future__ import annotations
import hashlib, html, json, re, sys, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
CONFIG_PATH=ROOT/'data'/'companies.json'
OUTPUT_PATH=ROOT/'data'/'jobs.json'
MAX_AGE_DAYS=7
CUTOFF=datetime.now(timezone.utc)-timedelta(days=MAX_AGE_DAYS)

TARGET_TITLES=[
 r'account executive',r'account manager',r'key account',r'strategic account',r'enterprise account',
 r'client partner',r'account director',r'client director',r'sales manager',r'sales director',
 r'head of sales',r'commercial manager',r'commercial director',r'business development',
 r'partnership',r'alliances?',r'partner manager',r'channel manager',r'territory manager',
 r'regional sales',r'enterprise sales',r'strategic sales',r'customer growth',r'revenue manager',
 r'מנהל(?:ת)? לקוחות',r'מנהל(?:ת)? תיקי לקוחות',r'מנהל(?:ת)? מכירות',r'מנהל(?:ת)? פיתוח עסקי',
 r'מנהל(?:ת)? שותפויות',r'מנהל(?:ת)? שותפים',r'מנהל(?:ת)? ערוצים',r'לקוחות מפתח',r'לקוחות אסטרטגיים'
]
EXCLUDED_TITLES=[
 r'\bsdr\b',r'\bbdr\b',r'sales development',r'business development representative',r'inside sales',
 r'sales engineer',r'solutions? engineer',r'presales',r'pre-sales',r'customer success',r'customer support',
 r'technical support',r'technical account manager',r'product marketing',r'marketing manager',r'intern',
 r'student',r'recruit',r'representative',r'associate',r'entry level',r'junior',r'מכירות טלפוניות',
 r'נציג(?:ת)? מכירות',r'שירות לקוחות',r'תמיכה'
]
ISRAEL_TERMS=[r'\bisrael\b',r'tel[ -]?aviv',r'herzliya',r'ra[\'’]?anana',r'petah[ -]?tikva',r'ramat[ -]?gan',r'bnei[ -]?brak',r'kfar[ -]?saba',r'hod[ -]?hasharon',r'netanya',r'haifa',r'yokneam',r'jerusalem',r'caesarea',r'rehovot',r'beer[ -]?sheva',r'rishon',r'holon',r'modi.?in',r'remote.*israel',r'ישראל',r'תל אביב',r'הרצליה',r'רעננה',r'פתח תקווה',r'רמת גן',r'בני ברק',r'כפר סבא',r'הוד השרון',r'נתניה',r'חיפה',r'יקנעם',r'ירושלים',r'קיסריה',r'רחובות',r'באר שבע',r'ראשון לציון',r'חולון']
NON_ISRAEL_TERMS=[r'\bjapan\b',r'\blondon\b',r'\bnew york\b',r'\bgermany\b',r'\bfrance\b',r'\bspain\b',r'\bitaly\b',r'\bsingapore\b',r'\bindia\b',r'\baustralia\b',r'\bunited states\b',r'\busa\b',r'\bcanada\b',r'\bpoland\b',r'\bnetherlands\b']
PREFERRED_TERMS=[(r'enterprise',18,'Enterprise'),(r'strategic',15,'Strategic Accounts'),(r'account executive',14,'Account Executive'),(r'client partner',13,'Client Partner'),(r'key account',12,'Key Accounts'),(r'account manager',10,'Account Management'),(r'business development',10,'Business Development'),(r'partnership|alliance|partner manager|channel',9,'Partnerships'),(r'director|head of|סמנכ',8,'Leadership'),(r'regional|global|territory',7,'Regional'),(r'senior|principal',6,'Senior'),(r'c-level|executive stakeholders?|cio|cto|vp',6,'C-Level'),(r'complex sales|long sales cycle|multi.?stakeholder',6,'Complex Sales'),(r'cloud|data|ai|software|saas|infrastructure|network|cyber',5,'Technology'),(r'existing accounts?|upsell|cross.?sell|expansion|farmer',5,'Expansion')]
SEARCH_TITLES=['"Account Executive"','"Account Manager"','"Strategic Account Manager"','"Enterprise Account Executive"','"Business Development Manager"','"Sales Manager"','"Sales Director"','"Client Partner"','"Key Account Manager"','"Partnerships Manager"','"Partner Manager"','"Commercial Manager"','"מנהל לקוחות"','"מנהל מכירות"','"מנהל פיתוח עסקי"','"מנהל שותפויות"']
SEARCH_SITES=[('LinkedIn','site:linkedin.com/jobs/view'),('AllJobs','site:alljobs.co.il'),('JobMaster','site:jobmaster.co.il'),('Drushim','site:drushim.co.il'),('Career site','(careers OR jobs OR greenhouse OR lever OR ashby OR workdayjobs OR smartrecruiters OR comeet)')]

def now_iso(): return datetime.now(timezone.utc).isoformat()
def request_text(url,accept='text/html,application/xhtml+xml,application/json'):
 req=Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; JobRadar/4.0)','Accept':accept,'Accept-Language':'he-IL,he;q=0.9,en;q=0.8'})
 with urlopen(req,timeout=35) as response:return response.read().decode('utf-8',errors='replace')
def get_json(url): return json.loads(request_text(url,'application/json'))
def clean(value): return re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',html.unescape(str(value or '')))).strip()
def matches(patterns,text): return any(re.search(p,text or '',re.I) for p in patterns)
def parse_date(value):
 if not value:return None
 try:
  dt=datetime.fromisoformat(str(value).strip().replace('Z','+00:00'));return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
 except ValueError:
  try:return parsedate_to_datetime(str(value)).astimezone(timezone.utc)
  except Exception:return None
def is_recent(v):
 dt=parse_date(v);return bool(dt and dt>=CUTOFF)
def is_target_role(title): return matches(TARGET_TITLES,title) and not matches(EXCLUDED_TITLES,title)
def is_israel(location,description='',title=''):
 loc=clean(location)
 if matches(NON_ISRAEL_TERMS,loc) and not matches(ISRAEL_TERMS,loc):return False
 return matches(ISRAEL_TERMS,f'{loc} {title} {description[:1600]}')
def stable_id(source,company,external_id,url): return f"{source[:2]}-{hashlib.sha1(f'{source}|{company}|{external_id}|{url}'.encode()).hexdigest()[:18]}"
def score_job(title,location,description):
 text=f'{title} {location} {description}'.lower();score,tags,reasons=38,[],[]
 for pattern,boost,tag in PREFERRED_TERMS:
  if re.search(pattern,text,re.I):score+=boost;tags.append(tag) if tag not in tags else None
 if re.search(r'enterprise|strategic|key account|אסטרטג',text):reasons.append('מכירה וניהול של לקוחות אסטרטגיים')
 if re.search(r'c-level|executive|cio|cto|vp|הנהלה',text):reasons.append('עבודה מול הנהלות ומקבלי החלטות')
 if re.search(r'upsell|cross.?sell|expansion|existing account|הרחבת',text):reasons.append('הרחבת פעילות בתוך לקוחות קיימים')
 return min(99,score),tags[:5],' · '.join((reasons or ['תפקיד מכירות B2B שעשוי להתאים לניסיון שלך'])[:2])
def normalize_job(*,source,company,external_id,title,location,description,posted_at,url):
 title,location,description,url=clean(title),clean(location),clean(description),str(url or '').strip()
 if not title or not url or not is_target_role(title) or not is_israel(location,description,title) or not is_recent(posted_at):return None
 dt=parse_date(posted_at);score,tags,reason=score_job(title,location,description)
 return {'id':stable_id(source,company,str(external_id),url),'company':company or 'לא צוין','title':title,'location':location or 'Israel','posted_at':dt.isoformat() if dt else now_iso(),'url':url,'score':score,'israel':True,'tags':tags,'reason':reason,'source':source}
def fetch_greenhouse(company,token,_):
 payload=get_json(f'https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true');out=[]
 for item in payload.get('jobs',[]):
  job=normalize_job(source='greenhouse',company=company,external_id=item.get('id',''),title=item.get('title',''),location=(item.get('location') or {}).get('name',''),description=item.get('content',''),posted_at=item.get('updated_at'),url=item.get('absolute_url',''))
  if job:out.append(job)
 return out
def fetch_lever(company,token,config):
 domain='api.eu.lever.co' if config.get('region')=='eu' else 'api.lever.co';payload=get_json(f'https://{domain}/v0/postings/{token}?mode=json');out=[]
 for item in payload:
  cat=item.get('categories') or {};locs=cat.get('allLocations') or [];location=', '.join(locs) if locs else cat.get('location','');created=item.get('createdAt');posted=datetime.fromtimestamp(created/1000,tz=timezone.utc).isoformat() if isinstance(created,(int,float)) else None
  job=normalize_job(source='lever',company=company,external_id=item.get('id',''),title=item.get('text',''),location=location,description=' '.join(clean(item.get(k,'')) for k in ('descriptionPlain','additionalPlain')),posted_at=posted,url=item.get('hostedUrl',''))
  if job:out.append(job)
 return out
def fetch_ashby(company,token,_):
 payload=get_json(f'https://api.ashbyhq.com/posting-api/job-board/{token}');out=[]
 for item in payload.get('jobs',[]):
  job=normalize_job(source='ashby',company=company,external_id=item.get('id') or item.get('jobUrl',''),title=item.get('title',''),location=item.get('location',''),description=item.get('descriptionHtml') or item.get('descriptionPlain') or '',posted_at=item.get('publishedAt') or item.get('updatedAt'),url=item.get('jobUrl') or item.get('applyUrl',''))
  if job:out.append(job)
 return out
def rss_items(query):
 root=ET.fromstring(request_text(f'https://www.bing.com/search?format=rss&setlang=he&q={quote_plus(query)}','application/rss+xml,text/xml'));return [{c.tag:(c.text or '') for c in item} for item in root.findall('./channel/item')]
def source_name(url,fallback):
 host=urlparse(url).netloc.lower()
 for needle,name in [('linkedin.com','LinkedIn'),('alljobs.co.il','AllJobs'),('jobmaster.co.il','JobMaster'),('drushim.co.il','Drushim')]:
  if needle in host:return name
 return fallback
def infer_company(title,url):
 for sep in [' - ',' | ',' at ',' ב-']:
  parts=title.split(sep)
  if len(parts)>1:
   c=clean(parts[-1])
   if 1<len(c)<70 and not matches(TARGET_TITLES,c):return c
 host=urlparse(url).netloc.replace('www.','');return host.split('.')[0].title() if host else 'לא צוין'
def fetch_public_search():
 jobs,status,seen=[],[],set()
 for label,site_query in SEARCH_SITES:
  count=errors=0
  for title_query in SEARCH_TITLES:
   query=f'{title_query} (Israel OR ישראל OR "Tel Aviv" OR "מרכז") {site_query}'
   try:
    for item in rss_items(query):
     url,title,description,posted=clean(item.get('link')),clean(item.get('title')),clean(item.get('description')),item.get('pubDate')
     if not url or url in seen:continue
     seen.add(url);job=normalize_job(source=source_name(url,label),company=infer_company(title,url),external_id=url,title=title,location=f'Israel · {label}',description=description,posted_at=posted,url=url)
     if job:jobs.append(job);count+=1
   except Exception as exc:errors+=1;print(f'WARNING search {label}: {exc}',file=sys.stderr)
  status.append({'company':label,'source':'public-search','ok':errors<len(SEARCH_TITLES),'matches':count,'errors':errors})
 return jobs,status
FETCHERS={'greenhouse':fetch_greenhouse,'lever':fetch_lever,'ashby':fetch_ashby}
def main():
 config=json.loads(CONFIG_PATH.read_text(encoding='utf-8'));all_jobs=[];source_status=[]
 for company in config.get('companies',[]):
  if not company.get('enabled',True):continue
  name,ats,token=company['name'],company['ats'],company['token'];fetcher=FETCHERS.get(ats)
  if not fetcher:source_status.append({'company':name,'source':ats,'ok':False,'error':'unsupported ATS'});continue
  try:
   found=fetcher(name,token,company);all_jobs.extend(found);source_status.append({'company':name,'source':ats,'ok':True,'matches':len(found)})
  except Exception as exc:source_status.append({'company':name,'source':ats,'ok':False,'error':f'{type(exc).__name__}: {exc}'[:220]})
 web_jobs,web_status=fetch_public_search();all_jobs.extend(web_jobs);source_status.extend(web_status)
 dedup={}
 for job in all_jobs:
  key=re.sub(r'\W+','',f"{job['company']}|{job['title']}|{job['location']}".lower());cur=dedup.get(key)
  if not cur or (job['score'],job['posted_at'])>(cur['score'],cur['posted_at']):dedup[key]=job
 jobs=sorted(dedup.values(),key=lambda j:(j.get('posted_at',''),j.get('score',0)),reverse=True)
 payload={'generated_at':now_iso(),'jobs':jobs,'source_status':source_status,'summary':{'jobs':len(jobs),'sources_ok':sum(1 for s in source_status if s.get('ok')),'sources_failed':sum(1 for s in source_status if not s.get('ok')),'window_days':MAX_AGE_DAYS}}
 OUTPUT_PATH.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');print(f'Wrote {len(jobs)} jobs from the last {MAX_AGE_DAYS} days');return 0
if __name__=='__main__':raise SystemExit(main())