const STORAGE_KEY = 'jobradar-state-v2';
const SETTINGS_KEY = 'jobradar-settings';
const state = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
const settings = { alertScore: 95, emailThreshold: 3, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}') };
let jobs = [];
let metadata = {};
let showHidden = false;
const $ = (id) => document.getElementById(id);
const controls = ['q','company','freshness','score','statusFilter','onlyIsrael','onlyNew'];

function saveState(){ localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); }
function saveSettings(){ localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings)); }
function jobState(id){ return state[id] || {}; }
function daysOld(date){ if(!date) return 999; return Math.max(0, Math.floor((Date.now()-new Date(date).getTime())/86400000)); }
function isFresh(job){ return daysOld(job.posted_at) <= 1; }
function isUnread(job){ return !jobState(job.id).read; }
function fmtDate(v){ if(!v) return 'לא ידוע'; return new Intl.DateTimeFormat('he-IL',{dateStyle:'medium'}).format(new Date(v)); }
function fmtDateTime(v){ if(!v) return 'טרם עודכן'; return new Intl.DateTimeFormat('he-IL',{dateStyle:'medium',timeStyle:'short'}).format(new Date(v)); }
function relativeAge(v){ const d=daysOld(v); return d===0?'היום':d===1?'אתמול':`לפני ${d} ימים`; }

function setJobState(id,key,val,rerender=true){ state[id]={...jobState(id),[key]:val}; saveState(); if(rerender) render(); }
function markRead(id){ if(!jobState(id).read) setJobState(id,'read',true); }

function filtered(){
  const q=$('q').value.trim().toLowerCase(), company=$('company').value;
  const freshness=$('freshness').value, minScore=+$('score').value, status=$('statusFilter').value;
  return jobs.filter(j=>{
    const s=jobState(j.id);
    if(s.dismissed && !showHidden) return false;
    if(q && !`${j.title} ${j.company} ${j.location} ${(j.tags||[]).join(' ')}`.toLowerCase().includes(q)) return false;
    if(company && j.company!==company) return false;
    if(freshness!=='all' && daysOld(j.posted_at)>+freshness) return false;
    if((j.score||0)<minScore) return false;
    if($('onlyIsrael').checked && !j.israel) return false;
    if($('onlyNew').checked && !isUnread(j)) return false;
    if(status==='unread' && !isUnread(j)) return false;
    if(status==='saved' && !s.saved) return false;
    if(!['all','unread','saved'].includes(status) && s.status!==status) return false;
    return true;
  }).sort((a,b)=>Number(isUnread(b))-Number(isUnread(a)) || (b.score-a.score) || new Date(b.posted_at)-new Date(a.posted_at));
}

function renderStats(){
  const active=jobs.filter(j=>!jobState(j.id).dismissed);
  const unread=active.filter(isUnread).length;
  const saved=active.filter(j=>jobState(j.id).saved).length;
  const applied=active.filter(j=>['applied','interview','offer'].includes(jobState(j.id).status)).length;
  $('stats').innerHTML=[['משרות פעילות',active.length],['לא נקראו',unread],['מועדפים',saved],['בתהליך',applied]].map(([t,n])=>`<div class="stat"><strong>${n}</strong><span>${t}</span></div>`).join('');
  const banner=$('newBanner');
  banner.hidden=!unread;
  banner.innerHTML=unread?`🟢 יש לך <strong>${unread}</strong> משרות שעדיין לא קראת.`:'';
}

function renderStatus(){
  const ok=metadata.summary?.sources_ok ?? 0, failed=metadata.summary?.sources_failed ?? 0;
  $('dataStatus').textContent=`עדכון אחרון: ${fmtDateTime(metadata.generated_at)} · ${ok} מקורות פעילים${failed?` · ${failed} נכשלו זמנית`:''}`;
}

function render(){
  renderStats(); renderStatus();
  const list=filtered(); $('resultCount').textContent=`${list.length} משרות מוצגות`;
  $('jobs').innerHTML=''; $('empty').hidden=!!list.length;
  list.forEach(j=>{
    const node=$('jobTemplate').content.cloneNode(true), card=node.querySelector('.job-card'), s=jobState(j.id);
    card.dataset.id=j.id;
    if(isUnread(j)) card.classList.add('unread-card');
    if(s.saved) card.classList.add('saved-card');
    if(s.dismissed) card.classList.add('dismissed-card');
    if(['applied','interview','offer'].includes(s.status)) card.classList.add('applied-card');
    node.querySelector('.company-logo').textContent=(j.company||'?').slice(0,2).toUpperCase();
    node.querySelector('.title').textContent=j.title;
    node.querySelector('.meta').textContent=`${j.company} · ${j.location||'מיקום לא צוין'} · ${relativeAge(j.posted_at)} · ${j.source||'Career site'}`;
    node.querySelector('.why').textContent=j.reason||'';
    node.querySelector('.score').textContent=`${j.score||0}%`;
    const badges=node.querySelector('.badges');
    if(isUnread(j)) badges.insertAdjacentHTML('beforeend','<span class="badge unread">לא נקראה</span>');
    if(isFresh(j)) badges.insertAdjacentHTML('beforeend','<span class="badge new">חדשה</span>');
    (j.tags||[]).slice(0,4).forEach(t=>{ const span=document.createElement('span'); span.className='badge'; span.textContent=t; badges.appendChild(span); });
    const a=node.querySelector('.apply'); a.href=j.url||'#'; a.onclick=()=>markRead(j.id);
    node.querySelector('.title').onclick=()=>markRead(j.id);
    node.querySelector('.save').textContent=s.saved?'★ נשמר':'☆ שמור';
    node.querySelector('.save').onclick=()=>setJobState(j.id,'saved',!s.saved);
    const tracker=node.querySelector('.tracker'); tracker.value=s.status||'none'; tracker.onchange=()=>setJobState(j.id,'status',tracker.value);
    node.querySelector('.dismiss').textContent=s.dismissed?'החזר':'לא רלוונטי';
    node.querySelector('.dismiss').onclick=()=>setJobState(j.id,'dismissed',!s.dismissed);
    $('jobs').appendChild(node);
  });
}

async function load(){
  const btn=$('refreshBtn'); btn.disabled=true; btn.textContent='מרענן...';
  try{
    const res=await fetch(`data/jobs.json?t=${Date.now()}`,{cache:'no-store'}); if(!res.ok) throw new Error('לא ניתן לטעון נתונים');
    const payload=await res.json(); jobs=payload.jobs||[]; metadata=payload;
    const companySelect=$('company'), current=companySelect.value;
    companySelect.innerHTML='<option value="">כל החברות</option>';
    [...new Set(jobs.map(j=>j.company))].sort().forEach(c=>{ const option=document.createElement('option'); option.value=c; option.textContent=c; companySelect.appendChild(option); });
    companySelect.value=current;
    localStorage.setItem('jobradar-last-visit',new Date().toISOString());
    render();
  }catch(e){ document.querySelector('main').insertAdjacentHTML('afterbegin',`<div class="error">${e.message}. פתח את האתר דרך GitHub Pages.</div>`); }
  finally{ btn.disabled=false; btn.textContent='רענון עכשיו'; }
}

controls.forEach(id=>$(id).addEventListener('input',render));
$('refreshBtn').onclick=load;
$('markAllRead').onclick=()=>{ jobs.forEach(j=>state[j.id]={...jobState(j.id),read:true}); saveState(); render(); };
$('showHidden').onclick=()=>{ showHidden=!showHidden; $('showHidden').textContent=showHidden?'הסתר מוסתרות':'הצג מוסתרות'; render(); };
$('clearState').onclick=()=>{ if(confirm('לאפס את כל הקריאות, המועדפים והסטטוסים?')){ localStorage.removeItem(STORAGE_KEY); location.reload(); } };
$('settingsBtn').onclick=()=>{ $('alertScore').value=String(settings.alertScore); $('emailThreshold').value=String(settings.emailThreshold); $('settingsDialog').showModal(); };
$('saveSettings').onclick=()=>{ settings.alertScore=+$('alertScore').value; settings.emailThreshold=+$('emailThreshold').value; saveSettings(); };

load();