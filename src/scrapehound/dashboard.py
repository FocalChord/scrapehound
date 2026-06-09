"""Static dashboard generator.

scrapehound commits state/*.json on every run, so a static site can render the
current state with no backend. `scrapehound dashboard --out <dir>` writes
data.json (aggregated from config + state) and a self-contained index.html.
Serve <dir> with GitHub Pages.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .config import load_sources

_INDEX_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>scrapehound</title>
<style>
  :root{color-scheme:light dark;--bg:#0b0c0f;--card:#15171c;--mut:#8a909b;--line:#262a31;--acc:#5b9dff;--sale:#ff5b6e}
  *{box-sizing:border-box}body{margin:0;font:15px/1.45 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;background:var(--bg);color:#e8eaed}
  header{padding:28px 20px 8px;max-width:1100px;margin:0 auto}
  h1{margin:0;font-size:24px;letter-spacing:-.02em}h1 span{color:var(--mut);font-weight:400}
  .meta{color:var(--mut);font-size:13px;margin-top:4px}
  main{max-width:1100px;margin:0 auto;padding:8px 20px 60px}
  .src{margin-top:28px}.src h2{font-size:16px;margin:0 0 2px;display:flex;gap:8px;align-items:baseline}
  .tag{font-size:11px;color:var(--mut);border:1px solid var(--line);border-radius:999px;padding:1px 8px}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px;margin-top:12px}
  .item{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;display:flex;flex-direction:column;gap:6px}
  .item img{width:100%;height:120px;object-fit:contain;border-radius:8px;background:#fff}
  .item a{color:#e8eaed;text-decoration:none;font-weight:600;font-size:13px;line-height:1.3}
  .price{font-size:16px;font-weight:700}.was{color:var(--mut);text-decoration:line-through;font-weight:400;font-size:13px;margin-left:6px}
  .badge{color:var(--sale);font-size:12px;font-weight:700}
  .chips{display:flex;flex-wrap:wrap;gap:4px;margin-top:2px}
  .chip{font-size:11px;color:var(--mut);background:#1c1f26;border-radius:6px;padding:1px 6px}
  .empty{color:var(--mut);font-size:13px;margin-top:8px}
</style></head>
<body>
<header><h1>scrapehound <span>dashboard</span></h1><div class="meta" id="meta"></div></header>
<main id="app"></main>
<script>
const money=v=>v==null?"":"$"+Number(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
fetch("data.json").then(r=>r.json()).then(d=>{
  document.getElementById("meta").textContent =
    `${d.sources.length} sources · ${d.sources.reduce((a,s)=>a+s.count,0)} items · updated ${new Date(d.generated_at).toLocaleString()}`;
  const app=document.getElementById("app");
  for(const s of d.sources){
    const sec=document.createElement("section");sec.className="src";
    sec.innerHTML=`<h2>${s.key} <span class="tag">${s.type}</span> <span class="tag">→ ${s.bot}</span> <span class="tag">${s.count}</span></h2>`;
    if(!s.items.length){sec.insertAdjacentHTML("beforeend",`<div class="empty">no items yet</div>`);}
    else{
      const g=document.createElement("div");g.className="grid";
      for(const it of s.items){
        const chips=Object.entries(it.attrs||{}).filter(([,v])=>v!=null&&v!=="").slice(0,4)
          .map(([k,v])=>`<span class="chip">${k}: ${Array.isArray(v)?v.join("/"):v}</span>`).join("");
        const price=it.price!=null?`<div class="price">${money(it.price)}${it.on_sale?`<span class="was">${money(it.was_price)}</span> <span class="badge">${it.percent_off}% off</span>`:""}</div>`:"";
        g.insertAdjacentHTML("beforeend",
          `<div class="item">${it.image?`<img loading="lazy" src="${it.image}">`:""}
           <a href="${it.url||"#"}" target="_blank" rel="noopener">${it.title}</a>${price}
           <div class="chips">${chips}</div></div>`);
      }
      sec.appendChild(g);
    }
    app.appendChild(sec);
  }
}).catch(e=>{document.getElementById("app").innerHTML=`<div class="empty">could not load data.json</div>`});
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
