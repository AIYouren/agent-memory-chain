#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""记忆之间的「边」—— 从各记忆文件的 [[wikilink]] 抽出来，给网状图用。

为什么单独一个模块: 边是**推导出来的**，不是手维护的 —— 单一来源是那 125 个 .md 里的
[[链接]] 本身。仪表板(_chain_dash.py)和完整性检查(_gen_index.py 以后)都从这儿取，
别再各写一份(会漂)。

三种目标要分开(实测 14 处断链里两类是不同毛病):
  memory    目标就是本目录的记忆文件       -> 真边
  skill     目标是技能名(gsb-pairwise-annotation / browser-use …) -> 命名空间没分开, 画成"技能"节点
  missing   目标既不是记忆也不是技能, 或里面写的是中文句子 -> 真断链, 该修
跑法:
  PYTHONUTF8=1 python _links.py            # 人看的摘要
  PYTHONUTF8=1 python _links.py --json     # 给仪表板/检查用的 payload
  PYTHONUTF8=1 python _links.py --check    # 只列断链, 有断链则 exit 1
"""
import io
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REG = HERE / "_registry.json"
SKILLS = Path.home() / ".claude" / "skills"

WIKI = re.compile(r"\[\[([^\[\]]+)\]\]")
FM_DESC = re.compile(r'^description:\s*"?(.+?)"?\s*$', re.M)
# 中文/空格/标点出现在 [[]] 里 = 写的是句子不是 slug(实测 1 处)
NOT_SLUG = re.compile(r"[\s，。、；：！？]|[一-鿿]")
FENCE = re.compile(r"```.*?```", re.S)
INLINE_CODE = re.compile(r"`[^`\n]*`")


def strip_code(text):
    """抽链接前先去掉围栏块与行内代码。
    ⛔ 反引号里的 [[链接]] 是在**讲语法**, 不是真链接 —— 不剥的话
    chain-memory-system.md 里那句 `` `[[链接]]` `` 会被当成一处断链(实测误报)。"""
    return INLINE_CODE.sub(" ", FENCE.sub(" ", text))


def _wildcard(explicit):
    """[[a|b]] 取 a; [[a#标题]] 取 a。"""
    t = explicit.split("|")[0].split("#")[0].strip()
    return t


def read_registry():
    if not REG.exists():
        return {}
    return json.load(io.open(REG, encoding="utf-8"))


def memory_files():
    """本目录下的记忆文件 slug(排除 MEMORY.md 和 _ 前缀工具笔记? 不排除 —— _recall_note 也是记忆)。"""
    return sorted(p.stem for p in HERE.glob("*.md") if p.name != "MEMORY.md")


def desc_of(slug):
    p = HERE / (slug + ".md")
    if not p.exists():
        return ""
    head = io.open(p, encoding="utf-8", errors="replace").read(1600)
    m = FM_DESC.search(head)
    if m:
        return m.group(1).strip()
    # 没 frontmatter 就取一级标题
    h = re.search(r"^#\s+(.+)$", head, re.M)
    return h.group(1).strip() if h else ""


def skill_names():
    if not SKILLS.is_dir():
        return set()
    return {p.name for p in SKILLS.iterdir() if p.is_dir()}


def _mtime(slug):
    """记忆文件的修改时间(YYYY-MM-DD)。分链轨按时间排, 热库文件没日期字段只能用它。"""
    try:
        return time.strftime("%Y-%m-%d", time.localtime((HERE / (slug + ".md")).stat().st_mtime))
    except OSError:
        return ""


def membership(reg, slugs):
    """记忆归属: 链 id / 主题域 / unfiled。

    链归属优先取 registry 的 dm_crosswalk(链 -> 它的 deep-memory slug 列表), 这是现成的归属表;
    再加 active[].file(那条链的主档)。剩下的按 domains 归档, 再没有就 unfiled。
    """
    own = {}
    for a in reg.get("active", []):
        cid = a["id"]
        got = set()
        if a.get("file"):
            got.add(a["file"])
        got.add(cid)
        cw = (reg.get("dm_crosswalk") or {}).get(cid) or {}
        for k in ("experience", "knowledge"):
            for s in cw.get(k) or []:
                if s in slugs:
                    got.add(s)
        for s in got:
            if s in slugs:
                own.setdefault(s, cid)
    for dom, lst in (reg.get("domains") or {}).items():
        for s in lst:
            if s in slugs:
                own.setdefault(s, dom)
    return own


def build():
    slugs = memory_files()
    slugset = set(slugs)
    skills = skill_names()
    reg = read_registry()
    own = membership(reg, slugset)

    edges, broken = [], []
    for slug in slugs:
        text = io.open(HERE / (slug + ".md"), encoding="utf-8", errors="replace").read()
        for raw in WIKI.findall(strip_code(text)):
            tgt = _wildcard(raw)
            if not tgt or tgt == slug:
                continue
            if tgt in slugset:
                edges.append({"source": slug, "target": tgt})
            else:
                kind = "skill" if tgt in skills else ("malformed" if NOT_SLUG.search(tgt) else "missing")
                broken.append({"target": tgt, "kind": kind, "from": slug})

    # 去重(同一对多处引用只留一条边) + 度
    seen, dedup = set(), []
    for e in edges:
        k = (e["source"], e["target"])
        if k in seen:
            continue
        seen.add(k)
        dedup.append(e)

    deg = {}
    for e in dedup:
        deg[e["source"]] = deg.get(e["source"], 0) + 1
        deg[e["target"]] = deg.get(e["target"], 0) + 1
    indeg = {}
    for e in dedup:
        indeg[e["target"]] = indeg.get(e["target"], 0) + 1

    nodes = [{"id": s, "label": s, "desc": desc_of(s), "deg": deg.get(s, 0),
              "in": indeg.get(s, 0), "own": own.get(s, "unfiled"),
              # 热库文件自己没有日期字段, 用文件修改时间当"时间" —— 分链轨要按时间排
              "mtime": _mtime(s),
              "chain": own.get(s, "unfiled") if own.get(s, "unfiled") in
                       {a["id"] for a in reg.get("active", [])} else ""}
             for s in slugs]
    return {"nodes": nodes, "edges": dedup, "broken": broken,
            "slugset": slugset, "own": own, "reg": reg}


def summary(d):
    nodes, edges, broken = d["nodes"], d["edges"], d["broken"]
    iso = [n["id"] for n in nodes if n["deg"] == 0]
    print("记忆文件 %d 个 | 去重后真边 %d 条" % (len(nodes), len(edges)))
    print("孤立节点(一条链接都没有) %d 个: %s" % (len(iso), ", ".join(iso[:8]) + ("…" if len(iso) > 8 else "")))
    print("入度 Top8: %s" % ", ".join("%s(%d)" % (n["id"], n["in"]) for n in sorted(nodes, key=lambda x: -x["in"])[:8]))
    own = d["own"]
    cnt = {}
    for s in d["slugset"]:
        cnt[own.get(s, "unfiled")] = cnt.get(own.get(s, "unfiled"), 0) + 1
    print("归属: 链 %d / 主题域 %d / unfiled %d" % (
        sum(v for k, v in cnt.items() if k in {a["id"] for a in d["reg"].get("active", [])}),
        sum(v for k, v in cnt.items() if k in (d["reg"].get("domains") or {})),
        cnt.get("unfiled", 0)))
    bk = {}
    for b in broken:
        bk.setdefault(b["kind"], set()).add(b["target"])
    print("断链 %d 处 / %d 个目标 —— 技能名 %d, 真缺 %d, 写成句子 %d" % (
        len(broken), len({b["target"] for b in broken}),
        len(bk.get("skill", ())), len(bk.get("missing", ())), len(bk.get("malformed", ()))))
    for b in broken:
        if b["kind"] != "skill":
            print("   [%s] %s  <- %s" % (b["kind"], b["target"], b["from"]))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    d = build()
    if "--json" in sys.argv:
        out = {"nodes": d["nodes"], "edges": d["edges"],
               "broken": sorted({(b["target"], b["kind"]) for b in d["broken"]})}
        print(json.dumps(out, ensure_ascii=False))
        return 0
    summary(d)
    if "--check" in sys.argv:
        real = [b for b in d["broken"] if b["kind"] != "skill"]
        return 1 if real else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
