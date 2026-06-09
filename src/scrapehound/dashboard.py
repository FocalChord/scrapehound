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

from .config import load_sources

_INDEX_HTML = r"""<!doctype html>
<html lang="en" data-theme="dark"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>scrapehound</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#08090d; --bg2:#0c0e13; --card:#13151c; --card2:#171922;
  --line:rgba(255,255,255,.07); --line2:rgba(255,255,255,.12);
  --txt:#eef1f6; --mut:#8b93a3; --faint:#5b626f;
  --acc:#7aa2ff; --acc2:#b794ff; --sale:#ff6b81; --ok:#37d399;
  --shadow:0 10px 30px rgba(0,0,0,.45);
}
[data-theme="light"]{
  --bg:#f6f7fb; --bg2:#eef0f6; --card:#fff; --card2:#fbfcfe;
  --line:rgba(10,12,20,.08); --line2:rgba(10,12,20,.14);
  --txt:#10131a; --mut:#5c6472; --faint:#9aa1ad; --shadow:0 10px 30px rgba(20,30,60,.10);
}
*{box-sizing:border-box}
html,body{margin:0}
body{font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg); color:var(--txt); -webkit-font-smoothing:antialiased; min-height:100vh}
.glow{position:fixed;inset:0;z-index:0;pointer-events:none;
  background:radial-gradient(60% 50% at 50% -10%, rgba(122,162,255,.18), transparent 70%),
             radial-gradient(40% 40% at 90% 0%, rgba(183,148,255,.12), transparent 70%)}
.wrap{position:relative;z-index:1;max-width:1180px;margin:0 auto;padding:0 22px}
header{display:flex;align-items:center;justify-content:space-between;padding:22px 0 8px}
.brand{display:flex;align-items:center;gap:11px;font-weight:800;font-size:19px;letter-spacing:-.02em}
.brand .logo{width:30px;height:30px}
.brand b{background:linear-gradient(120deg,var(--acc),var(--acc2));-webkit-background-clip:text;background-clip:text;color:transparent}
.iconbtn{width:38px;height:38px;border-radius:11px;border:1px solid var(--line);background:var(--card);
  color:var(--txt);cursor:pointer;display:grid;place-items:center;transition:.18s}
.iconbtn:hover{border-color:var(--line2);transform:translateY(-1px)}
.hero{padding:18px 0 6px}
.hero h1{font-size:clamp(26px,4vw,40px);line-height:1.05;letter-spacing:-.03em;margin:0 0 6px;font-weight:800}
.hero h1 em{font-style:normal;background:linear-gradient(120deg,var(--acc),var(--acc2));-webkit-background-clip:text;background-clip:text;color:transparent}
.hero p{color:var(--mut);margin:0 0 18px;max-width:560px}
.stats{display:flex;flex-wrap:wrap;gap:10px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 16px;min-width:120px}
.stat .n{font-size:22px;font-weight:800;letter-spacing:-.02em}
.stat .l{font-size:12px;color:var(--mut);margin-top:2px;display:flex;align-items:center;gap:6px}
.live{width:7px;height:7px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 0 rgba(55,211,153,.6);animation:pulse 2s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(55,211,153,.5)}70%{box-shadow:0 0 0 7px rgba(55,211,153,0)}100%{box-shadow:0 0 0 0 rgba(55,211,153,0)}}
.toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:22px 0 4px}
.search{flex:1;min-width:220px;position:relative}
.search input{width:100%;padding:12px 14px 12px 40px;border-radius:13px;border:1px solid var(--line);
  background:var(--card);color:var(--txt);font-size:14px;outline:none;transition:.18s}
.search input:focus{border-color:var(--acc)}
.search svg{position:absolute;left:13px;top:50%;transform:translateY(-50%);color:var(--faint)}
.toggle{display:flex;align-items:center;gap:8px;background:var(--card);border:1px solid var(--line);
  border-radius:13px;padding:0 14px;height:44px;cursor:pointer;user-select:none;font-size:13px;color:var(--mut);transition:.18s}
.toggle:hover{border-color:var(--line2)} .toggle.on{color:var(--txt);border-color:var(--sale)}
.toggle .sw{width:34px;height:20px;border-radius:999px;background:var(--line2);position:relative;transition:.18s}
.toggle .sw::after{content:"";position:absolute;top:2px;left:2px;width:16px;height:16px;border-radius:50%;background:#fff;transition:.18s}
.toggle.on .sw{background:var(--sale)} .toggle.on .sw::after{left:16px}
section.src{margin-top:34px}
.sh{display:flex;align-items:center;gap:10px;margin-bottom:14px}
.sh h2{font-size:17px;font-weight:700;letter-spacing:-.01em;margin:0}
.badge{font-size:11px;font-weight:600;color:var(--mut);border:1px solid var(--line);border-radius:999px;padding:2px 9px}
.badge.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.count{margin-left:auto;font-size:13px;color:var(--faint)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(218px,1fr));gap:14px}
.card{background:linear-gradient(180deg,var(--card),var(--card2));border:1px solid var(--line);
  border-radius:16px;padding:13px;display:flex;flex-direction:column;gap:9px;transition:.2s;
  opacity:0;transform:translateY(8px);animation:rise .5s forwards}
@keyframes rise{to{opacity:1;transform:none}}
.card:hover{transform:translateY(-3px);border-color:var(--line2);box-shadow:var(--shadow)}
.thumb{aspect-ratio:1/1;border-radius:12px;background:#fff;display:grid;place-items:center;overflow:hidden}
.thumb img{width:100%;height:100%;object-fit:contain;padding:8px}
.thumb.none{background:var(--bg2);color:var(--faint);font-size:24px}
.title{font-size:13px;font-weight:600;line-height:1.32;color:var(--txt);text-decoration:none;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:34px}
.title:hover{color:var(--acc)}
.row{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.price{font-size:18px;font-weight:800;letter-spacing:-.02em}
.was{font-size:13px;color:var(--faint);text-decoration:line-through;font-weight:500}
.off{font-size:11px;font-weight:700;color:#fff;background:linear-gradient(120deg,var(--sale),#ff8f6b);
  border-radius:999px;padding:2px 8px;margin-left:auto}
.chips{display:flex;flex-wrap:wrap;gap:5px}
.chip{font-size:11px;color:var(--mut);background:rgba(255,255,255,.04);border:1px solid var(--line);border-radius:7px;padding:2px 7px}
[data-theme="light"] .chip{background:rgba(10,12,20,.03)}
.chip.ok{color:var(--ok);border-color:rgba(55,211,153,.3)}
.empty{color:var(--faint);font-size:13px;padding:6px 0}
.hl{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:14px;margin-top:14px}
.hl .card{border-color:rgba(255,107,129,.25)}
footer{color:var(--faint);font-size:13px;text-align:center;padding:40px 0;border-top:1px solid var(--line);margin-top:48px}
footer a{color:var(--mut);text-decoration:none}
.hidden{display:none!important}
</style></head>
<body>
<div class="glow"></div>
<div class="wrap">
  <header>
    <div class="brand">
      <svg class="logo" viewBox="0 0 32 32" fill="none"><defs><linearGradient id="g" x1="0" y1="0" x2="32" y2="32">
        <stop stop-color="#7aa2ff"/><stop offset="1" stop-color="#b794ff"/></linearGradient></defs>
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
    <h1>What the pack is <em>tracking</em></h1>
    <p>A live snapshot of every watched product across your sources, rebuilt after each scrape.</p>
    <div class="stats" id="stats"></div>
    <div class="toolbar">
      <div class="search">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>
        <input id="q" type="search" placeholder="Search products…" autocomplete="off">
      </div>
      <div class="toggle" id="saleonly"><span class="sw"></span><span>On sale only</span></div>
    </div>
  </div>
  <main id="app"></main>
  <footer>Built by <a href="https://github.com/FocalChord/scrapehound">scrapehound</a> · <span id="gen"></span></footer>
</div>
<script>
const money=v=>v==null?"":"$"+Number(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
let DATA=null, saleOnly=false, query="";

function cardHTML(it){
  const chips=Object.entries(it.attrs||{}).filter(([,v])=>v!=null&&v!==""&&(!Array.isArray(v)||v.length))
    .slice(0,4).map(([k,v])=>{const val=Array.isArray(v)?v.join("/"):v;
      const ok=/available|in stock/i.test(String(val));
      return `<span class="chip${ok?" ok":""}">${esc(k)}: ${esc(val)}</span>`;}).join("");
  const price=it.price!=null?`<div class="row"><span class="price">${money(it.price)}</span>${
    it.on_sale?`<span class="was">${money(it.was_price)}</span><span class="off">-${it.percent_off}%</span>`:""}</div>`:"";
  const thumb=it.image?`<div class="thumb"><img loading="lazy" src="${esc(it.image)}" onerror="this.parentElement.classList.add('none');this.remove()"></div>`
                      :`<div class="thumb none">◎</div>`;
  return `<a class="card" href="${esc(it.url||"#")}" target="_blank" rel="noopener" data-t="${esc((it.title||"").toLowerCase())}" data-sale="${it.on_sale?1:0}">
    ${thumb}<span class="title">${esc(it.title)}</span>${price}<div class="chips">${chips}</div></a>`;
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
    html+=`<section class="src" data-hl><div class="sh"><h2>🔥 On sale now</h2><span class="count">${onsale.length}</span></div>
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
document.getElementById("q").addEventListener("input",e=>{query=e.target.value.trim().toLowerCase();filter();});
document.getElementById("saleonly").addEventListener("click",e=>{saleOnly=!saleOnly;e.currentTarget.classList.toggle("on",saleOnly);filter();});
const themeBtn=document.getElementById("theme"), root=document.documentElement;
if(localStorage.theme)root.dataset.theme=localStorage.theme;
themeBtn.addEventListener("click",()=>{root.dataset.theme=root.dataset.theme==="dark"?"light":"dark";localStorage.theme=root.dataset.theme;});
fetch("data.json").then(r=>r.json()).then(d=>{DATA=d;render();})
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
            })
        items.sort(key=lambda x: float(x["price"]) if x["price"] else 1e12)
        data["sources"].append({"key": key, "type": s.type, "bot": s.bot,
                                "notify": s.notify, "count": len(items), "items": items})
    (out_dir / "data.json").write_text(json.dumps(data, indent=1))
    (out_dir / "index.html").write_text(_INDEX_HTML)
    return out_dir
