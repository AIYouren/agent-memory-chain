#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
链式记忆地图生成器 (2026-10-12)

读 _registry.json(链卡) + ~/.deep-memory/cold-notes/raw.jsonl(记忆条目),
产出单文件、离线可开的 HTML 地图: 域 -> 链 -> 资产/记忆条目。

跑法:  PYTHONUTF8=1 python _chain_map.py [--out <file.html>]
纯标准库, 无需 venv。
"""
import io
import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REG = os.path.join(HERE, "_registry.json")
OUT = os.path.join(HERE, "memory-chain-map.html")

# 冷库位置: 环境变量 > 默认家目录
def cold_path():
    ws = os.environ.get("DEEP_MEMORY_WORKSPACE") or os.path.join(
        os.path.expanduser("~"), ".deep-memory")
    return os.path.join(ws, "cold-notes", "raw.jsonl")


def load_registry():
    return json.load(io.open(REG, encoding="utf-8"))


def load_cold():
    """读冷库, 返回条目列表。坏行跳过, 不抛。"""
    p = cold_path()
    out = []
    if not os.path.exists(p):
        return out, p
    for i, line in enumerate(io.open(p, encoding="utf-8", errors="replace"), 1):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        d["_line"] = i
        out.append(d)
    return out, p


def chain_hits(cold, chain):
    """一条链命中的冷库条目: project 精确命中, 或内容含任一别名。"""
    keys = [chain["id"]] + chain.get("aliases", [])
    hit = []
    for e in cold:
        blob = " ".join(str(e.get(k, "")) for k in ("topic", "content", "tags", "skill"))
        if e.get("project") in keys or any(k and k in blob for k in keys):
            hit.append(e)
    return hit


def build_data(reg, cold):
    chains = []
    for a in reg["active"]:
        hits = chain_hits(cold, a)
        # 归一到域: 找 active id 出现在哪个域里(域索引只列文件 slug, 用 file 反查)
        dom = None
        f = a.get("file", a["id"])
        for d, slugs in reg["domains"].items():
            if a["id"] in slugs or f in slugs:
                dom = d
                break
        chains.append({
            "id": a["id"],
            "title": a.get("title", a["id"]),
            "aliases": a.get("aliases", []),
            "status": a.get("status", ""),
            "next": a.get("next", ""),
            "work": a.get("work", ""),
            "scripts": a.get("scripts", ""),
            "deliverable": a.get("deliverable", ""),
            "assets": a.get("assets", {}),
            "domain": dom or "(未归域)",
            "mem_count": len(hits),
            "mem": [{
                "line": e.get("_line"),
                "topic": str(e.get("topic", ""))[:120],
                "type": e.get("memory_type", ""),
                "project": e.get("project", ""),
                "skill": e.get("skill", ""),
                "tags": e.get("tags", ""),
            } for e in hits[-40:]],  # 每条链最多留 40 条, 防爆
        })
    # 域 -> 链
    dom_map = defaultdict(list)
    for c in chains:
        dom_map[c["domain"]].append(c["id"])
    return {
        "chains": chains,
        "domains": {d: ids for d, ids in dom_map.items()},
        "cold_total": len(cold),
        "cold_projects": Counter(
            e.get("project", "(none)") for e in cold).most_common(15),
    }


HTML = u"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>链式记忆地图</title>
<style>
:root{--bg:#0e1116;--panel:#161b22;--line:#283040;--fg:#e6edf3;--dim:#8b949e;
--acc:#58a6ff;--ok:#3fb950;--warn:#d29922;--bad:#f85149;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
header{padding:20px 24px;border-bottom:1px solid var(--line);
display:flex;align-items:baseline;gap:16px;flex-wrap:wrap}
h1{font-size:19px;margin:0;font-weight:600}
.stat{color:var(--dim);font-size:13px}
.stat b{color:var(--acc);font-weight:600}
.wrap{display:grid;grid-template-columns:260px 1fr;height:calc(100vh - 74px)}
nav{border-right:1px solid var(--line);overflow:auto;padding:12px}
nav .dom{margin:10px 0 4px;color:var(--dim);font-size:11px;
text-transform:uppercase;letter-spacing:.06em}
nav a{display:block;padding:6px 10px;border-radius:6px;color:var(--fg);
text-decoration:none;font-size:13px;white-space:nowrap;overflow:hidden;
text-overflow:ellipsis}
nav a:hover{background:var(--panel)}
nav a.on{background:var(--acc);color:#04121f;font-weight:600}
nav a .n{float:right;color:var(--dim);font-size:11px}
nav a.on .n{color:#04121f}
main{overflow:auto;padding:20px 24px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
padding:18px 20px;margin-bottom:16px}
.card h2{margin:0 0 4px;font-size:17px}
.card .id{color:var(--dim);font-size:12px;font-family:ui-monospace,monospace}
.row{margin:10px 0}
.row .k{color:var(--dim);font-size:11px;text-transform:uppercase;
letter-spacing:.05em;margin-bottom:3px}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{background:#1f2630;border:1px solid var(--line);border-radius:20px;
padding:2px 10px;font-size:12px;color:var(--fg)}
.chip.acc{border-color:var(--acc);color:var(--acc)}
.chip.warn{border-color:var(--warn);color:var(--warn)}
.next{background:#101820;border-left:3px solid var(--warn);padding:8px 12px;
border-radius:0 6px 6px 0;font-size:13px;white-space:pre-wrap}
.mem{font-size:12px;border-bottom:1px solid var(--line);padding:6px 0;
display:grid;grid-template-columns:52px 1fr 90px;gap:10px;align-items:baseline}
.mem .ln{color:var(--dim);font-family:ui-monospace,monospace}
.mem .tp{color:var(--dim);font-size:11px;text-align:right}
.mem .t{color:var(--fg)}
.empty{color:var(--dim);font-size:12px;padding:8px 0}
.legend{color:var(--dim);font-size:12px;margin-top:6px}
code{background:#1f2630;padding:1px 5px;border-radius:4px;font-size:12px}
</style></head><body>
<header>
<h1>链式记忆地图</h1>
<span class="stat">链 <b id="nc"></b> · 冷库条目 <b id="nk"></b> · 生成 <b>__GEN__</b></span>
</header>
<div class="wrap">
<nav id="nav"></nav>
<main id="main"></main>
</div>
<script>
const DATA = __DATA__;
const byId = {}; DATA.chains.forEach(c=>byId[c.id]=c);

function el(t,cls,txt){const e=document.createElement(t);
if(cls)e.className=cls;if(txt!=null)e.textContent=txt;return e;}

function renderNav(){
  const nav=document.getElementById('nav');
  Object.keys(DATA.domains).sort().forEach(d=>{
    nav.appendChild(el('div','dom',d));
    DATA.domains[d].forEach(id=>{
      const c=byId[id];
      const a=el('a',null,c.title);
      a.href='#'+id; a.dataset.id=id;
      const n=el('span','n',c.mem_count); a.appendChild(n);
      a.onclick=e=>{e.preventDefault();show(id);};
      nav.appendChild(a);
    });
  });
}
function chip(t,cls){return el('span','chip'+(cls?' '+cls:''),t);}
function renderChain(c){
  const m=document.getElementById('main'); m.innerHTML='';
  const card=el('div','card');
  card.appendChild(el('h2',null,c.title));
  card.appendChild(el('div','id',c.id+'  ·  '+c.domain));
  if(c.status){const r=el('div','row');
    r.appendChild(el('div','k','状态'));r.appendChild(el('div',null,c.status));card.appendChild(r);}
  if(c.next){const r=el('div','row');
    r.appendChild(el('div','k','下一步'));r.appendChild(el('div','next',c.next));card.appendChild(r);}
  if(c.work){const r=el('div','row');
    r.appendChild(el('div','k','目录'));
    r.appendChild(el('div',null,c.work));card.appendChild(r);}
  if(c.deliverable){const r=el('div','row');
    r.appendChild(el('div','k','成品'));r.appendChild(el('div',null,c.deliverable));card.appendChild(r);}
  const a=c.assets||{};
  const al=el('div','row'); al.appendChild(el('div','k','资产'));
  const cs=el('div','chips');
  (c.aliases||[]).forEach(x=>cs.appendChild(chip(x,'acc')));
  (a.scripts||[]).forEach(x=>cs.appendChild(chip('脚本 '+x)));
  (a.skills||[]).forEach(x=>cs.appendChild(chip('skill '+x)));
  (a.mcp||[]).forEach(x=>cs.appendChild(chip('mcp '+x,'warn')));
  (a.dirs||[]).forEach(x=>cs.appendChild(chip('目录 '+x)));
  if(!cs.children.length)cs.appendChild(chip('(未登记资产)'));
  al.appendChild(cs); card.appendChild(al);
  m.appendChild(card);
  // 记忆条目
  const mc=el('div','card');
  mc.appendChild(el('h2',null,'链上记忆条目 ('+c.mem_count+')'));
  if(!c.mem.length){mc.appendChild(el('div','empty','冷库里还没有这条链的条目'));}
  else{
    const rev=c.mem.slice().reverse();
    rev.forEach(e=>{
      const d=el('div','mem');
      d.appendChild(el('span','ln','#'+e.line));
      d.appendChild(el('span','t',e.topic||'(无题)'));
      d.appendChild(el('span','tp',e.type));
      mc.appendChild(d);
    });
    if(c.mem_count>40)mc.appendChild(el('div','empty','… 只显示最近 40 条'));
  }
  m.appendChild(mc);
}
function show(id){
  document.querySelectorAll('nav a').forEach(a=>
    a.classList.toggle('on',a.dataset.id===id));
  renderChain(byId[id]);
}
document.getElementById('nc').textContent=DATA.chains.length;
document.getElementById('nk').textContent=DATA.cold_total;
renderNav();
show(DATA.chains[0]&&DATA.chains[0].id);
</script></body></html>"""


def main():
    reg = load_registry()
    cold, cp = load_cold()
    data = build_data(reg, cold)
    import datetime
    data["cold_path"] = cp
    html = (HTML
            .replace("__DATA__", json.dumps(data, ensure_ascii=False))
            .replace("__GEN__", datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
    out = OUT
    for i, a in enumerate(sys.argv):
        if a == "--out" and i + 1 < len(sys.argv):
            out = sys.argv[i + 1]
    io.open(out, "w", encoding="utf-8").write(html)
    sys.stdout.reconfigure(encoding="utf-8")
    print("已写出 %s (%d 链 / 冷库 %d 条 / %d 字符)"
          % (out, len(data["chains"]), data["cold_total"], len(html)))
    print("冷库源: %s" % cp)
    # 每条链命中数
    for c in data["chains"]:
        print("  %-26s %3d 条" % (c["id"], c["mem_count"]))


if __name__ == "__main__":
    main()
