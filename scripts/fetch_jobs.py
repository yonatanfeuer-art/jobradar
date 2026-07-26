#!/usr/bin/env python3
import json, re, hashlib, html
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
CONFIG=json.loads((ROOT/'data/companies.json').read_text(encoding='utf-8'))

INCLUDE=[r'account executive',r'account manager',r'sales',r'business development',r'client partner',r'client director',r'commercial',r'partnership',r'alliance',r'channel',r'country manager']
EXCLUDE=[r'\bsdr\b',r'\bbdr\b',r'inside sales',r'sales engineer',r'presales',r'pre-sales',r'customer success',r'support',r'intern',r'student']
ISRAEL=[r'israel',r'tel aviv',r'herzliya',r'raanana',r'ra\'anana',r'petah tikva',r'ramat gan',r'haifa',r'jerusalem',r'י?שראל']

def get_json(url):
    req=Request(url,headers={'User-Agent':'JobRadar/1.0'})
    with urlopen(req,timeout=30) as r:return json.load(r)

def clean(s): return re.sub('<[^>]+>',' ',html.unescape(s or '')).strip()
def matches(patterns,text): return any(re.search(p,text,re.I) for p in patterns)
def score(title,location,description):
    text=f'{title} {location} {description}'.lower(); s=45; reasons=[]; tags=[]
    boosts=[('enterprise',16,'Enterprise'),('strategic',14,'Strategic'),('account executive',14,'Account Executive'),('account manager',10,'Account Management'),('business development',10,'Business Development'),('client partner',12,'Client Partner'),('director',8,'Leadership'),('regional',7,'Regional'),('senior',6,'Senior'),('c-level',6,'C-Level')]
    for k,v,t in boosts:
        if k in text:s+=v;tags.append(t)
    s=min(99,s)
    if 'enterprise' in text: reasons.append('מכירות Enterprise')
    if 'strategic' in text: reasons.append('לקוחות אסטרטגיים')
    if 'c-level' in text or 'executive' in text: reasons.append('עבודה מול הנהלות')
    if not reasons: reasons.append('תפקיד Sales רלוונטי')
    return s,tags,' · '.join(reasons)

def greenhouse(company,token):
    raw=get_json(f'https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true')
    out=[]
    for j in raw.get('jobs',[]):
        title=j.get('title',''); loc=(j.get('location') or {}).get('name',''); desc=clean(j.get('content',''))
        text=f'{title} {loc} {desc}'
        if not matches(INCLUDE,title) or matches(EXCLUDE,title): continue
        israel=matches(ISRAEL,loc+' '+desc)
        if not israel: continue
        sc,tags,reason=score(title,loc,desc)
        out.append({'id':f"gh-{j.get('id')}",'company':company,'title':title,'location':loc,'posted_at':j.get('updated_at'),'url':j.get('absolute_url'),'score':sc,'israel':True,'tags':tags,'reason':reason})
    return out

def lever(company,token):
    raw=get_json(f'https://api.lever.co/v0/postings/{token}?mode=json')
    out=[]
    for j in raw:
        title=j.get('text',''); cats=j.get('categories') or {}; loc=cats.get('location',''); desc=clean(j.get('descriptionPlain') or j.get('description'))
        if not matches(INCLUDE,title) or matches(EXCLUDE,title): continue
        if not matches(ISRAEL,loc+' '+desc): continue
        sc,tags,reason=score(title,loc,desc)
        out.append({'id':'lv-'+hashlib.sha1((company+title+j.get('hostedUrl','')).encode()).hexdigest()[:16],'company':company,'title':title,'location':loc,'posted_at':datetime.now(timezone.utc).isoformat(),'url':j.get('hostedUrl'),'score':sc,'israel':True,'tags':tags,'reason':reason})
    return out

def main():
    jobs=[]; errors=[]
    for c in CONFIG['companies']:
        if not c.get('enabled'): continue
        try:
            fn={'greenhouse':greenhouse,'lever':lever}.get(c['ats'])
            if fn: jobs.extend(fn(c['name'],c['token']))
        except Exception as e: errors.append(f"{c['name']}: {e}")
    seen={};
    for j in jobs: seen[j['id']]=j
    payload={'generated_at':datetime.now(timezone.utc).isoformat(),'jobs':list(seen.values()),'errors':errors}
    (ROOT/'data/jobs.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"Saved {len(seen)} jobs; {len(errors)} source errors")

if __name__=='__main__': main()
