const state = JSON.parse(localStorage.getItem('jobradar-state') || '{}');
let jobs = [];
const $ = (id) => document.getElementById(id);
const controls = ['q','company','freshness','score','onlyIsrael','onlyNew'];

function saveState(){localStorage.setItem('jobradar-state', JSON.stringify(state));}
function daysOld(date){if(!date)return 999; return Math.floor((Date.now()-new Date(date).getTime())/86400000);}
function isNew(job){return daysOld(job.posted_at)<=1;}
function fmtDate(v){if(!v)return 'לא ידוע'; return new Intl.DateTimeFormat('he-IL',{dateStyle:'medium'}).format(new Date(v));}

function filtered(){
  const q=$('q').value.trim().toLowerCase(), company=$('company').value;
  const freshness=$('freshness').value, minScore=+$('score').value;
  return jobs.filter(j=>{
    if(state[j.id]?.dismissed) return false;
    if(q && !`${j.title} ${j.company} ${j.location}`.toLowerCase().includes(q)) return false;
    if(company && j.company!==company) return false;
    if(freshness!=='all' && daysOld(j.posted_at)>+freshness) return false;
    if((j.score||0)<minScore) return false;
    if($('onlyIsrael').checked && !j.israel) return false;
    if($('onlyNew').checked && !isNew(j)) return false;
    return true;
  }).sort((a,b)=>(b.score-a.score)||new Date(b.posted_at)-new Date(a.posted_at));
}

function renderStats(){
  const visible=jobs.filter(j=>!state[j.id]?.dismissed), fresh=visible.filter(isNew), top=visible.filter(j=>j.score>=90), applied=Object.values(state).filter(x=>x.applied).length;
  $('stats').innerHTML=[['משרות במאגר',visible.length],['חדשות היום',fresh.length],['התאמות 90%+',top.length],['הגשתי',applied]].map(([t,n])=>`<div class="stat"><strong>${n}</strong><span>${t}</span></div>`).join('');
}

function setJobState(id,key,val){state[id]={...(state[id]||{}),[key]:val};saveState();render();}
function render(){
  renderStats(); const list=filtered(); $('resultCount').textContent=`${list.length} משרות מוצגות`;
  $('jobs').innerHTML=''; $('empty').hidden=!!list.length;
  list.forEach(j=>{
    const node=$('jobTemplate').content.cloneNode(true); const card=node.querySelector('.job-card');
    card.dataset.id=j.id; node.querySelector('.company-logo').textContent=(j.company||'?').slice(0,2).toUpperCase();
    node.querySelector('.title').textContent=j.title; node.querySelector('.meta').textContent=`${j.company} · ${j.location||'מיקום לא צוין'} · ${fmtDate(j.posted_at)}`;
    node.querySelector('.why').textContent=j.reason||''; node.querySelector('.score').textContent=`${j.score||0}%`;
    const badges=node.querySelector('.badges');
    if(isNew(j)) badges.insertAdjacentHTML('beforeend','<span class="badge new">חדש</span>');
    (j.tags||[]).slice(0,4).forEach(t=>badges.insertAdjacentHTML('beforeend',`<span class="badge">${t}</span>`));
    const a=node.querySelector('.apply'); a.href=j.url||'#';
    const s=state[j.id]||{}; if(s.saved)card.classList.add('saved-card'); if(s.applied)card.classList.add('applied-card');
    node.querySelector('.save').textContent=s.saved?'נשמר':'שמור'; node.querySelector('.applied').textContent=s.applied?'הוגש ✓':'הגשתי';
    node.querySelector('.save').onclick=()=>setJobState(j.id,'saved',!s.saved);
    node.querySelector('.applied').onclick=()=>setJobState(j.id,'applied',!s.applied);
    node.querySelector('.dismiss').onclick=()=>setJobState(j.id,'dismissed',true);
    $('jobs').appendChild(node);
  });
}

async function load(){
  try{
    const res=await fetch(`data/jobs.json?t=${Date.now()}`); if(!res.ok)throw new Error('לא ניתן לטעון נתונים');
    const payload=await res.json(); jobs=payload.jobs||[];
    const companies=[...new Set(jobs.map(j=>j.company))].sort();
    companies.forEach(c=>$('company').insertAdjacentHTML('beforeend',`<option>${c}</option>`));
    render();
  }catch(e){document.querySelector('main').insertAdjacentHTML('afterbegin',`<div class="error">${e.message}. פתח את האתר דרך GitHub Pages ולא באמצעות לחיצה ישירה על הקובץ.</div>`);}
}
controls.forEach(id=>$(id).addEventListener('input',render));
$('refreshBtn').onclick=()=>location.reload();
$('clearState').onclick=()=>{if(confirm('לאפס את כל הסימונים?')){localStorage.removeItem('jobradar-state');location.reload();}};
load();
