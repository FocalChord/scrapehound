"""Static dashboard generator.

scrapehound commits state/*.json on every run, so a static site can render the
current state with no backend. `scrapehound dashboard --out <dir>` writes
data.json (aggregated from config + state) and a self-contained index.html.
Serve <dir> with GitHub/Cloudflare Pages.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from . import comps as comps_mod
from .config import load_comps, load_sources

_INDEX_HTML = r"""<!doctype html>
<html lang="en" data-theme="dark"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>scrapehound</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#0b0c0f; --bg2:#15181d; --card:#141619; --card2:#141619;
  --line:rgba(255,255,255,.08); --line2:rgba(255,255,255,.15);
  --txt:#e8eaef; --mut:#969ca8; --faint:#646b78;
  --acc:#6e8bf5; --acc2:#6e8bf5; --sale:#e0697e; --ok:#46b17c; --warn:#d6a35c;
  --shadow:0 8px 24px rgba(0,0,0,.35);
}
[data-theme="light"]{
  --bg:#fbfbfc; --bg2:#f4f5f7; --card:#ffffff; --card2:#ffffff;
  --line:rgba(17,20,28,.09); --line2:rgba(17,20,28,.16);
  --txt:#15181d; --mut:#5b626e; --faint:#9298a3;
  --acc:#4f6ef0; --acc2:#4f6ef0; --sale:#d6536c; --ok:#2f9e6a; --warn:#bd854a;
  --shadow:0 8px 24px rgba(20,28,50,.08);
}
*{box-sizing:border-box}
html,body{margin:0}
body{font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg); color:var(--txt); -webkit-font-smoothing:antialiased; min-height:100vh;
  font-feature-settings:"tnum" 1}
.glow{display:none}
.wrap{position:relative;z-index:1;max-width:1180px;margin:0 auto;padding:0 22px}
header{display:flex;align-items:center;justify-content:space-between;padding:22px 0 8px}
.brand{display:flex;align-items:center;gap:10px;font-weight:600;font-size:16px;letter-spacing:-.01em}
.brand .logo{width:26px;height:26px}
.brand b{color:var(--acc);font-weight:600}
.iconbtn{width:36px;height:36px;border-radius:9px;border:1px solid var(--line);background:var(--card);
  color:var(--mut);cursor:pointer;display:grid;place-items:center;transition:.15s}
.iconbtn:hover{border-color:var(--line2);color:var(--txt)}
.hero{padding:30px 0 12px}
.hero h1{font-size:clamp(22px,3vw,29px);line-height:1.15;letter-spacing:-.02em;margin:0 0 8px;font-weight:600}
.hero p{color:var(--mut);margin:0 0 22px;max-width:600px;font-size:14px;line-height:1.55}
.stats{display:flex;flex-wrap:wrap;gap:10px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:13px 16px;min-width:128px}
.stat .n{font-size:21px;font-weight:600;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.stat .l{font-size:11px;color:var(--mut);margin-top:4px;display:flex;align-items:center;gap:6px;text-transform:uppercase;letter-spacing:.05em}
.live{width:6px;height:6px;border-radius:50%;background:var(--ok)}
.toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:22px 0 4px}
.search{flex:1;min-width:220px;position:relative}
.search input{width:100%;padding:11px 14px 11px 38px;border-radius:10px;border:1px solid var(--line);
  background:var(--card);color:var(--txt);font-size:14px;outline:none;transition:.15s}
.search input:focus{border-color:var(--acc)}
.search svg{position:absolute;left:13px;top:50%;transform:translateY(-50%);color:var(--faint)}
.toggle{display:flex;align-items:center;gap:9px;background:var(--card);border:1px solid var(--line);
  border-radius:10px;padding:0 14px;height:42px;cursor:pointer;user-select:none;font-size:13px;color:var(--mut);transition:.15s}
.toggle:hover{border-color:var(--line2)} .toggle.on{color:var(--txt);border-color:var(--acc)}
.toggle .sw{width:32px;height:18px;border-radius:999px;background:var(--line2);position:relative;transition:.15s}
.toggle .sw::after{content:"";position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;background:#fff;transition:.15s}
.toggle.on .sw{background:var(--acc)} .toggle.on .sw::after{left:16px}
section.src{margin-top:38px}
.sh{display:flex;align-items:center;gap:10px;margin-bottom:16px}
.sh h2{font-size:15px;font-weight:600;letter-spacing:-.01em;margin:0}
.badge{font-size:11px;font-weight:500;color:var(--mut);border:1px solid var(--line);border-radius:6px;padding:2px 8px}
.badge.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:10px}
.count{margin-left:auto;font-size:12px;color:var(--faint)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);
  border-radius:12px;padding:13px;display:flex;flex-direction:column;gap:9px;transition:border-color .15s,transform .15s}
.card:hover{transform:translateY(-2px);border-color:var(--line2)}
.thumb{aspect-ratio:1/1;border-radius:9px;background:#fff;display:grid;place-items:center;overflow:hidden}
.thumb img{width:100%;height:100%;object-fit:contain;padding:8px}
.thumb.none{background:var(--bg2);color:var(--faint);font-size:22px}
.title{font-size:13px;font-weight:550;line-height:1.35;color:var(--txt);text-decoration:none;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:35px}
.title:hover{color:var(--acc)}
.row{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.price{font-size:17px;font-weight:600;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.was{font-size:12px;color:var(--faint);text-decoration:line-through;font-weight:400}
.off{font-size:10px;font-weight:600;color:var(--sale);background:transparent;
  border:1px solid color-mix(in srgb,var(--sale) 35%,transparent);border-radius:6px;padding:1px 7px;margin-left:auto}
.chips{display:flex;flex-wrap:wrap;gap:5px}
.age{font-size:11px;color:var(--faint);margin-top:auto;padding-top:2px}
.chip{font-size:11px;color:var(--mut);background:var(--bg2);border:1px solid var(--line);border-radius:6px;padding:2px 7px}
.chip.ok{color:var(--ok);border-color:color-mix(in srgb,var(--ok) 30%,transparent)}
.empty{color:var(--faint);font-size:13px;padding:8px 0}
.hl{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px;margin-top:14px}
.hl .card{border-color:color-mix(in srgb,var(--sale) 22%,transparent)}
footer{color:var(--faint);font-size:12px;text-align:center;padding:36px 0;border-top:1px solid var(--line);margin-top:48px}
footer a{color:var(--mut);text-decoration:none}
.hidden{display:none!important}
.tabs{display:flex;gap:26px;margin:30px 0 0;border-bottom:1px solid var(--line)}
.tab{padding:0 0 12px;border:none;border-bottom:2px solid transparent;
  background:transparent;color:var(--mut);cursor:pointer;font-size:14px;font-weight:550;font-family:inherit;transition:.15s;margin-bottom:-1px}
.tab:hover{color:var(--txt)}
.tab.on{color:var(--txt);border-bottom-color:var(--acc)}
.cpanel{background:var(--card);border:1px solid var(--line);
  border-radius:12px;padding:20px;margin-top:16px}
.cpanel h2{margin:0 0 3px;font-size:16px;font-weight:600;letter-spacing:-.01em}
.cpanel .sub{color:var(--mut);font-size:13px;margin-bottom:10px}
.cpanel .sub b{color:var(--txt);font-weight:600}
.sub2bar{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:18px}
.wtabs{display:flex;gap:6px;margin:6px 0 4px}
.wtab{font-size:12px;padding:5px 11px;border-radius:7px;border:1px solid var(--line);background:var(--bg2);
  color:var(--mut);cursor:pointer;font-family:inherit;transition:.15s}
.wtab:hover{color:var(--txt)} .wtab.on{color:var(--txt);border-color:var(--acc);background:color-mix(in srgb,var(--acc) 10%,transparent)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(96px,1fr));gap:10px;margin-bottom:18px}
.tile{background:var(--bg2);border:1px solid var(--line);border-radius:10px;padding:11px 13px}
.tile .n{font-size:19px;font-weight:600;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.tile .l{font-size:10px;color:var(--mut);margin-top:3px;text-transform:uppercase;letter-spacing:.05em}
.tile.lk{display:block;text-decoration:none;color:inherit;cursor:pointer;transition:.15s}
.tile.lk:hover{border-color:var(--acc)}
.tile.lk .l::after{content:" ↗";color:var(--faint)}
.tile.big{border-color:color-mix(in srgb,var(--acc) 28%,transparent);background:color-mix(in srgb,var(--acc) 7%,transparent)}
.tile.big .n{color:var(--acc)}
.charts{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:720px){.charts{grid-template-columns:1fr}}
.chart{background:var(--bg2);border:1px solid var(--line);border-radius:10px;padding:14px}
.chart h3{margin:0 0 10px;font-size:10px;color:var(--mut);font-weight:600;text-transform:uppercase;letter-spacing:.06em}
.chart svg{width:100%;height:auto;display:block}
.sold{margin-top:16px;border-top:1px solid var(--line);padding-top:6px}
.sold>summary{cursor:pointer;list-style:none;color:var(--mut);font-size:13px;font-weight:600;
  padding:8px 2px;display:flex;align-items:center;gap:8px;user-select:none}
.sold>summary::-webkit-details-marker{display:none}
.sold>summary .car{transition:.2s;color:var(--faint)}
.sold[open]>summary .car{transform:rotate(90deg)}
.sold>summary:hover{color:var(--txt)}
.solds{max-height:360px;overflow:auto;margin-top:6px;border:1px solid var(--line);border-radius:10px}
.srow{display:grid;grid-template-columns:40px 80px 1fr;gap:11px;align-items:center;
  padding:8px 12px;border-bottom:1px solid var(--line);font-size:13px}
.srow:last-child{border-bottom:none}
.srow:hover{background:var(--bg2)}
.srow .th{width:40px;height:40px;border-radius:8px;object-fit:contain;background:#fff}
.srow .th.none{width:40px;height:40px;border-radius:8px;background:var(--bg2)}
.srow .p{font-weight:700;font-variant-numeric:tabular-nums}
.srow .info{min-width:0}
.srow .info a{color:var(--txt);text-decoration:none;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.srow .info a:hover{color:var(--acc)}
.srow .sub2{font-size:11px;color:var(--mut);margin-top:3px;display:flex;gap:7px;flex-wrap:wrap;align-items:center}
.srow .loc{color:var(--faint)}
.srow.off{opacity:.6}
.kb{font-size:10px;font-weight:600;border-radius:5px;padding:2px 8px;border:1px solid var(--line);white-space:nowrap;letter-spacing:.02em}
.kb.au{color:var(--ok);background:color-mix(in srgb,var(--ok) 12%,transparent);border-color:color-mix(in srgb,var(--ok) 32%,transparent)}
.kb.bin{color:var(--mut);background:var(--bg2)}
.kb.bo{color:var(--warn);background:color-mix(in srgb,var(--warn) 12%,transparent);border-color:color-mix(in srgb,var(--warn) 32%,transparent)}
</style></head>
<body>
<div class="wrap">
  <header>
    <div class="brand">
      <svg class="logo" viewBox="0 0 32 32" fill="none"><defs><linearGradient id="g" x1="0" y1="0" x2="32" y2="32">
        <stop stop-color="#6e8bf5"/><stop offset="1" stop-color="#9db0fb"/></linearGradient></defs>
        <circle cx="16" cy="16" r="13" stroke="url(#g)" stroke-width="2" opacity=".5"/>
        <circle cx="16" cy="16" r="7" stroke="url(#g)" stroke-width="2" opacity=".8"/>
        <path d="M16 16 L27 9 A13 13 0 0 1 27 23 Z" fill="url(#g)" opacity=".28"/>
        <circle cx="16" cy="16" r="2.6" fill="url(#g)"/></svg>
      <span>scrape<b>hound</b></span>
    </div>
    <button class="iconbtn" id="theme" title="Toggle theme">
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg></button>
  </header>
  <div class="hero">
    <h1>Tracking &amp; market value</h1>
    <p>Live inventory across your watched sources, plus accumulated eBay sold-price comps — auction-clearing medians, percentiles, and price trends.</p>
    <div class="stats" id="stats"></div>
    <div class="toolbar">
      <div class="search">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>
        <input id="q" type="search" placeholder="Search products…" autocomplete="off">
      </div>
      <div class="toggle" id="saleonly"><span class="sw"></span><span>On sale only</span></div>
    </div>
  </div>
  <div class="tabs">
    <button class="tab on" data-tab="tracking">Tracking</button>
    <button class="tab" data-tab="comps">Market value</button>
    <button class="tab" data-tab="comps-au">AU market</button>
  </div>
  <main id="app"></main>
  <main id="comps" class="hidden"></main>
  <main id="comps-au" class="hidden"></main>
  <footer>Built by <a href="https://github.com/FocalChord/scrapehound">scrapehound</a> · <span id="gen"></span></footer>
</div>
<script>
const money=v=>v==null?"":"$"+Number(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
let DATA=null, saleOnly=false, query="";

function ago(iso){
  if(!iso) return "";
  const t=Date.parse(iso); if(isNaN(t)) return "";
  const days=Math.floor((Date.now()-t)/86400000);
  if(days<=0) return "listed today";
  if(days===1) return "listed 1 day ago";
  if(days<7) return `listed ${days} days ago`;
  if(days<31) return `listed ${Math.floor(days/7)}w ago`;
  if(days<365) return `listed ${Math.floor(days/30)}mo ago`;
  return `listed ${Math.floor(days/365)}y ago`;
}
function cardHTML(it){
  const chips=Object.entries(it.attrs||{}).filter(([,v])=>v!=null&&v!==""&&(!Array.isArray(v)||v.length))
    .slice(0,4).map(([k,v])=>{const val=Array.isArray(v)?v.join("/"):v;
      const ok=/available|in stock/i.test(String(val));
      return `<span class="chip${ok?" ok":""}">${esc(k)}: ${esc(val)}</span>`;}).join("");
  const price=it.price!=null?`<div class="row"><span class="price">${money(it.price)}</span>${
    it.on_sale?`<span class="was">${money(it.was_price)}</span><span class="off">-${it.percent_off}%</span>`:""}</div>`:"";
  const thumb=it.image?`<div class="thumb"><img loading="lazy" src="${esc(it.image)}" onerror="this.parentElement.classList.add('none');this.remove()"></div>`
                      :`<div class="thumb none">◎</div>`;
  const age=ago(it.first_seen);
  const aged=age?`<span class="age" title="first seen ${esc(it.first_seen)}${it.last_seen?" · last seen "+esc(it.last_seen):""}">${age}</span>`:"";
  return `<a class="card" href="${esc(it.url||"#")}" target="_blank" rel="noopener" data-t="${esc((it.title||"").toLowerCase())}" data-sale="${it.on_sale?1:0}">
    ${thumb}<span class="title">${esc(it.title)}</span>${price}<div class="chips">${chips}</div>${aged}</a>`;
}
function render(){
  const items=DATA.sources.flatMap(s=>s.items);
  const onsale=items.filter(i=>i.on_sale);
  document.getElementById("stats").innerHTML=[
    [DATA.sources.length,"sources",false],[items.length,"items tracked",false],
    [onsale.length,"on sale",false],[new Date(DATA.generated_at).toLocaleString([], {month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"}),"updated",true]
  ].map(([n,l,live])=>`<div class="stat"><div class="n">${n}</div><div class="l">${live?'<span class="live"></span>':""}${l}</div></div>`).join("");
  document.getElementById("gen").textContent="updated "+new Date(DATA.generated_at).toLocaleString();
  const app=document.getElementById("app");
  let html="";
  if(onsale.length){
    onsale.sort((a,b)=>(b.percent_off||0)-(a.percent_off||0));
    html+=`<section class="src" data-hl><div class="sh"><h2>On sale now</h2><span class="count">${onsale.length}</span></div>
      <div class="hl">${onsale.slice(0,8).map(cardHTML).join("")}</div></section>`;
  }
  for(const s of DATA.sources){
    html+=`<section class="src" data-src><div class="sh"><h2>${esc(s.key)}</h2>
      <span class="badge mono">${esc(s.type)}</span><span class="badge">→ ${esc(s.bot)}</span>
      <span class="count">${s.count} items</span></div>`;
    html+= s.items.length?`<div class="grid">${s.items.map(cardHTML).join("")}</div>`:`<div class="empty">no items yet</div>`;
    html+=`</section>`;
  }
  app.innerHTML=html;
  app.querySelectorAll(".card").forEach((c,i)=>c.style.animationDelay=(Math.min(i,20)*22)+"ms");
  filter();
}
function filter(){
  document.querySelectorAll("section[data-src],section[data-hl]").forEach(sec=>{
    let shown=0;
    sec.querySelectorAll(".card").forEach(c=>{
      const ok=(!query||c.dataset.t.includes(query))&&(!saleOnly||c.dataset.sale==="1");
      c.classList.toggle("hidden",!ok); if(ok)shown++;
    });
    sec.classList.toggle("hidden", shown===0 && (query||saleOnly));
  });
}
// ---- Market value (comps) tabs ----
let COMPS=[], COMPS_AU=[], cwin=90;
const m0=v=>v==null?"—":"$"+Number(v).toLocaleString(undefined,{maximumFractionDigits:0});
function tile(label,val,big){return `<div class="tile${big?" big":""}"><div class="n">${val}</div><div class="l">${esc(label)}</div></div>`;}
function histSVG(hist){
  if(!hist||!hist.length)return '<div class="empty">—</div>';
  const W=320,H=120,pad=18,n=hist.length,maxN=Math.max(...hist.map(b=>b.n),1),bw=(W-pad*2)/n;
  const bars=hist.map((b,i)=>{const h=(H-pad-14)*(b.n/maxN),x=pad+i*bw,y=H-14-h;
    return `<rect x="${(x+1).toFixed(1)}" y="${y.toFixed(1)}" width="${(bw-2).toFixed(1)}" height="${Math.max(h,0).toFixed(1)}" rx="2" fill="url(#cg)"><title>${m0(b.x0)}–${m0(b.x1)}: ${b.n}</title></rect>`;}).join("");
  return `<svg viewBox="0 0 ${W} ${H}"><defs><linearGradient id="cg" x1="0" y1="0" x2="0" y2="1">
    <stop stop-color="#6e8bf5"/><stop offset="1" stop-color="#9db0fb"/></linearGradient></defs>${bars}
    <text x="${pad}" y="${H-2}" fill="#8b93a3" font-size="9">${m0(hist[0].x0)}</text>
    <text x="${W-pad}" y="${H-2}" text-anchor="end" fill="#8b93a3" font-size="9">${m0(hist[hist.length-1].x1)}</text></svg>`;
}
function trendSVG(trend){
  const pts=(trend||[]).filter(t=>t.p50!=null);
  if(!pts.length)return '<div class="empty">—</div>';
  const W=320,H=120,pad=24,ys=pts.map(p=>p.p50),ymin=Math.min(...ys),ymax=Math.max(...ys),span=(ymax-ymin)||1;
  const X=i=>pad+(pts.length===1?(W-2*pad)/2:i*(W-2*pad)/(pts.length-1));
  const Y=v=>H-18-(H-30)*((v-ymin)/span);
  const line=pts.map((p,i)=>`${i?"L":"M"}${X(i).toFixed(1)} ${Y(p.p50).toFixed(1)}`).join(" ");
  const area=`M${X(0).toFixed(1)} ${H-18} `+pts.map((p,i)=>`L${X(i).toFixed(1)} ${Y(p.p50).toFixed(1)}`).join(" ")+` L${X(pts.length-1).toFixed(1)} ${H-18} Z`;
  const dots=pts.map((p,i)=>`<circle cx="${X(i).toFixed(1)}" cy="${Y(p.p50).toFixed(1)}" r="3" fill="#6e8bf5"><title>${esc(p.month)}: ${m0(p.p50)} (n=${p.n})</title></circle>`).join("");
  const labs=pts.map((p,i)=>`<text x="${X(i).toFixed(1)}" y="${H-4}" text-anchor="middle" fill="#5b626f" font-size="8">${esc(p.month.slice(2))}</text>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}"><path d="${area}" fill="rgba(110,139,245,.14)"/>
    <path d="${line}" fill="none" stroke="#6e8bf5" stroke-width="2"/>${dots}${labs}
    <text x="2" y="11" fill="#8b93a3" font-size="9">${m0(ymax)}</text>
    <text x="2" y="${H-20}" fill="#8b93a3" font-size="9">${m0(ymin)}</text></svg>`;
}
function tileLink(label,val,sale){
  const body=`<div class="n">${val}</div><div class="l">${esc(label)}</div>`;
  if(sale&&sale.url){
    const k=KIND_TAG[sale.kind]||"";
    return `<a class="tile lk" href="${esc(sale.url)}" target="_blank" rel="noopener" title="${esc(label)} — sold ${esc(sale.sold_date||"")}${k?" via "+k:""} — ${esc(sale.title||"")}">${body}</a>`;
  }
  return `<div class="tile">${body}</div>`;
}
const KIND_TAG={auction:"auction", fixed:"Buy It Now", offer:"Best Offer"};
function compPanel(c){
  const st=c.windows[cwin]||{}, rz=st.realized||{}, au=st.auction||{}, ct=st.counts||{};
  const span=c.span?`${c.span[0]} → ${c.span[1]}`:"";
  const tiles=rz.n?[
    tile("market value · p50",m0(rz.p50),true),
    tile("p90",m0(rz.p90)),tile("p95",m0(rz.p95)),
    tile(au.n?`auction p50 · n${au.n}`:"auction p50",au.n?m0(au.p50):"—"),
    tileLink("min",m0(rz.min),st.lo),tileLink("max",m0(rz.max),st.hi),
    tile("realized sales",rz.n),
  ].join("")
    :`<div class="empty">no realized sales in the ${cwin}-day window</div>`;
  const bd=`<span class="kb au">${ct.auction||0} auction</span>
    <span class="kb bin">${ct.fixed||0} buy-it-now</span>
    <span class="kb bo">${ct.offer||0} best-offer · excluded</span>`;
  return `<div class="cpanel"><h2>${esc(c.key)}</h2>
    <div class="sub">“${esc(c.query||"")}” · <b>${esc(c.currency)}</b> · ${c.total} comps${span?" · "+esc(span):""}</div>
    <div class="sub2bar">${bd}</div>
    <div class="tiles">${tiles}</div>
    <div class="charts">
      <div class="chart"><h3>Realized price distribution (90d)</h3>${histSVG(c.hist)}</div>
      <div class="chart"><h3>Realized median by month</h3>${trendSVG(c.trend)}</div></div>
    ${soldList(c)}</div>`;
}
const KIND={auction:'<span class="kb au">Auction</span>',
  fixed:'<span class="kb bin">Buy It Now</span>',
  offer:'<span class="kb bo">Best offer</span>'};
function soldRow(r){
  const d=r.sold_date?r.sold_date.slice(2):"";  // YY-MM-DD
  const title=esc(r.title||"(untitled)");
  const link=r.url?`<a href="${esc(r.url)}" target="_blank" rel="noopener" title="${title}">${title}</a>`
                  :`<span title="${title}">${title}</span>`;
  const img=r.image?`<img class="th" loading="lazy" src="${esc(r.image)}" onerror="this.classList.add('none');this.removeAttribute('src')">`
                   :`<span class="th none"></span>`;
  const loc=r.location?`<span class="loc">${esc(r.location)}</span>`:"";
  const bids=(r.kind==="auction"&&r.bids)?`<span>${r.bids} bid${r.bids>1?"s":""}</span>`:"";
  return `<div class="srow${r.kind==="offer"?" off":""}">${img}<span class="p">${m0(r.price)}</span>
    <div class="info">${link}<div class="sub2">${KIND[r.kind]||""}<span>${esc(d)}</span>${loc}${bids}</div></div></div>`;
}
function soldList(c){
  const ls=c.listings||[];
  if(!ls.length)return "";
  return `<details class="sold"><summary><span class="car">▸</span>Show ${ls.length} sold listings (newest first)</summary>
    <div class="solds">${ls.map(soldRow).join("")}</div></details>`;
}
function renderComps(rootId, list, note){
  const root=document.getElementById(rootId);
  if(!list.length){root.innerHTML=`<div class="empty">${note||"No sold-price comps yet. Run <code>scrapehound comps collect</code>."}</div>`;return;}
  const sel=[30,90,365].map(w=>`<button class="wtab${w===cwin?" on":""}" data-w="${w}">${w}d</button>`).join("");
  const hdr=note?`<div class="sub" style="margin:4px 0 2px">${note}</div>`:"";
  root.innerHTML=hdr+`<div class="wtabs">${sel}</div>`+list.map(compPanel).join("");
  root.querySelectorAll(".wtab").forEach(b=>b.onclick=()=>{cwin=+b.dataset.w;renderComps(rootId,list,note);});
}
function renderActiveComps(){
  renderComps("comps", COMPS);
  renderComps("comps-au", COMPS_AU,
    "Sold by sellers <b>located in Australia</b> only — the local market, with eBay's international sellers excluded. Sparse for globally-traded items.");
}
document.querySelectorAll(".tab").forEach(t=>t.addEventListener("click",()=>{
  document.querySelectorAll(".tab").forEach(x=>x.classList.toggle("on",x===t));
  const tab=t.dataset.tab, tracking=tab==="tracking";
  document.getElementById("app").classList.toggle("hidden",!tracking);
  document.getElementById("comps").classList.toggle("hidden",tab!=="comps");
  document.getElementById("comps-au").classList.toggle("hidden",tab!=="comps-au");
  document.querySelector(".toolbar").classList.toggle("hidden",!tracking);
  if(!tracking)renderActiveComps();
}));
document.getElementById("q").addEventListener("input",e=>{query=e.target.value.trim().toLowerCase();filter();});
document.getElementById("saleonly").addEventListener("click",e=>{saleOnly=!saleOnly;e.currentTarget.classList.toggle("on",saleOnly);filter();});
const themeBtn=document.getElementById("theme"), root=document.documentElement;
if(localStorage.theme)root.dataset.theme=localStorage.theme;
themeBtn.addEventListener("click",()=>{root.dataset.theme=root.dataset.theme==="dark"?"light":"dark";localStorage.theme=root.dataset.theme;});
fetch("data.json").then(r=>r.json()).then(d=>{DATA=d;COMPS=d.comps||[];COMPS_AU=d.comps_au||[];render();})
  .catch(()=>{document.getElementById("app").innerHTML='<div class="empty">could not load data.json</div>';});
</script></body></html>
"""


def build_site(out: str = "docs", config_dir: str = "config", state_dir: str = "state") -> Path:
    sources = load_sources(f"{config_dir}/sources.yaml")
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    data = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "sources": []}
    for key, s in sources.items():
        if not s.dashboard:          # tracked + alerting, but hidden from the dashboard
            continue
        path = Path(state_dir) / f"{key}.json"
        records = json.loads(path.read_text()) if path.exists() else {}
        items = []
        for r in records.values():
            price = r.get("price")
            was = r.get("was_price")
            on_sale = bool(was and price and float(was) > float(price))
            items.append({
                "title": r.get("title", r.get("id", "")), "price": price, "was_price": was,
                "on_sale": on_sale,
                "percent_off": round((1 - float(price) / float(was)) * 100) if on_sale else None,
                "url": r.get("url"), "image": r.get("image"), "attrs": r.get("attrs", {}),
                "first_seen": r.get("first_seen"), "last_seen": r.get("last_seen"),
            })
        items.sort(key=lambda x: float(x["price"]) if x["price"] else 1e12)
        data["sources"].append({"key": key, "type": s.type, "bot": s.bot,
                                "notify": s.notify, "count": len(items), "items": items})
    data["comps"] = _build_comps(config_dir, state_dir)
    data["comps_au"] = _build_comps(config_dir, state_dir, scope="au")
    (out_dir / "data.json").write_text(json.dumps(data, indent=1))
    (out_dir / "index.html").write_text(_INDEX_HTML)
    return out_dir


def _histogram(prices: list[float], bins: int = 12) -> list[dict]:
    """Bin sale prices for a distribution chart, clipping the top to p95 so a
    single outlier doesn't flatten the bars."""
    if not prices:
        return []
    lo = min(prices)
    hi = comps_mod.percentile(prices, 0.95) or max(prices)
    if hi <= lo:
        hi = lo + 1
    width = (hi - lo) / bins
    counts = [0] * bins
    for p in prices:
        idx = min(int((min(p, hi) - lo) / width), bins - 1)
        counts[max(idx, 0)] += 1
    return [{"x0": round(lo + i * width), "x1": round(lo + (i + 1) * width), "n": c}
            for i, c in enumerate(counts)]


def _build_comps(config_dir: str, state_dir: str, scope: str = "") -> list[dict]:
    """Per comps key (for one market scope: "" global, "au" Australia-located):
    windowed stats, monthly p50 trend, a 90d histogram, and the listing rows."""
    today = dt.datetime.now(dt.timezone.utc).date()
    out = []
    for key, s in load_comps(f"{config_dir}/sources.yaml").items():
        st = comps_mod.stats(key, state_dir, today=today, scope=scope)
        if not st["total"]:
            continue
        cur = st["currency"]
        rows = comps_mod.CompStore(key, state_dir, scope).load()
        prices90 = comps_mod._window_prices(rows, 90, cur, None, today)
        listings = sorted(
            ({"title": r["title"], "price": r["price"], "condition": r.get("condition"),
              "sold_date": r["sold_date"], "url": r.get("url"),
              "kind": comps_mod._kind(r), "location": r.get("location"),
              "image": r.get("image"), "bids": r.get("bids")}
             for r in rows if r.get("currency") == cur),
            key=lambda r: r["sold_date"], reverse=True)
        out.append({
            "key": key,
            "query": s.options().get("query"),
            "currency": cur,
            "total": st["total"],
            "span": st.get("span"),
            "windows": st["windows"],
            "trend": comps_mod.monthly_trend(key, state_dir, currency=cur, scope=scope),
            "hist": _histogram(prices90),
            "listings": listings,
        })
    return out
