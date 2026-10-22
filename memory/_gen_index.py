#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
从 _registry.json + 各记忆文件的 description(frontmatter) 重生成 MEMORY.md。

为什么不手写索引:
  1. MEMORY.md 每轮全量进上下文, 必须是"能扫的", 手写会漂
  2. 改一处(加别名/改下一步)要同步 4 个地方 = 下次必然漏 = 回到"检索不上"

跑法:  PYTHONUTF8=1 python _gen_index.py [--dry-run]
"""
import io
import json
import os
import re
import sys

import _memlog

HERE = os.path.dirname(os.path.abspath(__file__))
REG = os.path.join(HERE, "_registry.json")
OUT = os.path.join(HERE, "MEMORY.md")
LOG_ROWS = 10                      # 日志表进 MEMORY.md 的行数(每轮全量注入, 别放太多)

FM_DESC = re.compile(r'^description:\s*"?(.+?)"?\s*$', re.M)


def read_registry():
    return json.load(io.open(REG, encoding="utf-8"))


def parse_existing_descriptions():
    """slug -> 一行说明。来源优先级:
      1. _desc_cache.json  (2026-10-07 加: §2 瘦身后 MEMORY.md 不再写描述, 靠它保命)
      2. 现有 MEMORY.md    (老版带描述时抓下来)
      3. 各文件 frontmatter
    """
    out = {}
    cache = os.path.join(HERE, "_desc_cache.json")
    if os.path.exists(cache):
        try:
            out.update({k: v for k, v in json.load(io.open(cache, encoding="utf-8")).items() if v})
        except Exception:
            pass
    if os.path.exists(OUT):
        for line in io.open(OUT, encoding="utf-8"):
            m = re.match(r"- \[([^\]]+)\]\([^)]+\)\s*(?:—|--)?\s*(.*)", line.rstrip())
            if m and m.group(2).strip():
                out.setdefault(m.group(1), m.group(2).strip())
    return out


def read_frontmatter_desc(slug):
    """记忆文件里若没进索引, 用 frontmatter 的 description 兜底。"""
    p = os.path.join(HERE, slug + ".md")
    if not os.path.exists(p):
        return None
    head = io.open(p, encoding="utf-8", errors="replace").read(2000)
    m = FM_DESC.search(head)
    return m.group(1).strip() if m else None


def all_slugs():
    """记忆文件。注意: `_` 前缀的也收(工具脚本旁的说明笔记), 只排除 MEMORY.md 和 .py/.cmd。"""
    return {
        f.rsplit(".", 1)[0]
        for f in os.listdir(HERE)
        if f.endswith(".md") and f != "MEMORY.md"
    }


def build(reg):
    descs = parse_existing_descriptions()
    have = all_slugs()

    # 主键 -> 域: 一个主键的"同域记忆" = 它出现过的所有域里、属于该域的兄弟记忆
    # (手工在 _registry.json 里没写 related, 就用 active[id] 的 id 本身所在域推断)
    related_slugs = {}

    # 主键 -> 真实记忆文件: 主键是短名(便于索引), 记忆文件是历史 slug
    primary_files = {a["id"]: a.get("file", a["id"]) for a in reg["active"]}

    # 反查表: 所有出现的 slug(主键同时登记它的真实文件)
    used = set()
    for a in reg["active"]:
        used.add(a["id"])
        used.add(primary_files[a["id"]])
    for lst in reg["domains"].values():
        used.update(lst)

    def line_for(slug):
        d = descs.get(slug) or read_frontmatter_desc(slug) or "(无说明)"
        if len(d) > 260:
            d = d[:257] + "..."
        return "- [%s](%s.md) — %s" % (slug, slug, d)

    out = []
    A = out.append
    A("# Memory Index")
    A("")
    A("> **这张表由 `_gen_index.py` 自动生成，别手改。**")
    A("> 改内容去改 `_registry.json`(主键/别名/下一步)或对应的记忆文件，跑")
    A("> `PYTHONUTF8=1 python _gen_index.py` 重生成。三库对照见 `_registry.json` 的 `dm_crosswalk`。")
    A("")
    A("**三库分工**：`MEMORY.md`(本表,每轮全量注入) → 记忆文件(主档) → `_registry.json`(主键) ；")
    A("deep-memory 热库/冷库是同一批事的压缩副本，对照在 `dm_crosswalk`；works 侧的状态在 `任务台账.md`。")
    A("")

    # ---- 0. 叫法对照 ----
    # ⛔ 2026-10-07 瘦身: 原来 1 行 1 个别名 = 90 行。改成每行 3 个, 行数砍 2/3。
    A("## 0. 你的叫法 → 查哪条")
    A("")
    A("> 你说话用的词常常和记忆的 slug 对不上，先在这里对一眼。")
    A("")
    alias_map = {}
    for a in reg["active"]:
        for al in a["aliases"]:
            alias_map.setdefault(al, a["id"])
    extra = reg.get("alias_extras", {})
    for al, target in extra.items():
        if al.startswith("_"):
            continue
        alias_map.setdefault(al, target)
    ordered = sorted(alias_map, key=lambda s: (len(s), s))
    pairs = ["%s → `%s`" % (al, alias_map[al]) for al in ordered]
    per_row = 5
    A("| " + " | ".join(["叫法"] * per_row) + " |")
    A("|" + "---|" * per_row)
    for i in range(0, len(pairs), per_row):
        row = pairs[i:i + per_row]
        while len(row) < per_row:
            row.append("")
        A("| " + " | ".join(row) + " |")
    A("")

    # ---- 1. 在跑的活 ----
    # ⛔ 2026-10-08 再压(目标全文件 <140 行): 每条固定 3 行 ——
    #    ① 主键+状态+目录+先读 ② 成品 ③ 下一步(卡点并进去)。
    #    「deep-memory 副本」整条删掉 —— 头部已指向 `dm_crosswalk`, 不必每轮重付 9 行。
    A("## 1. ★ 在跑的活（先看这里，每条都带下一步）")
    A("")
    for a in reg["active"]:
        loc_bits = ["`%s`" % a["work"]] if a.get("work") else []
        if a.get("scripts"):
            loc_bits.append("脚本 `%s`" % a["scripts"])
        if a.get("readme"):
            loc_bits.append("先读 `%s`" % a["readme"])
        meta = "`%s` → `%s.md` ｜ %s" % (a["id"], a.get("file", a["id"]), a.get("status", "—"))
        if loc_bits:
            meta += " ｜ " + " ".join(loc_bits)
        A("### %s" % a["title"])
        A("- %s" % meta)
        tail = ""
        if a.get("deliverable"):
            tail += "成品：%s" % a["deliverable"]
        if a.get("note"):
            tail += (" ｜ " if tail else "") + a["note"]
        if tail:
            A("- %s" % tail)
        nxt = ""
        if a.get("blocker"):
            nxt = "⛔ %s ｜ " % a["blocker"]
        if a.get("next"):
            nxt += a["next"]
        if nxt:
            A("- 下一步：%s" % nxt)
        A("")

    # ---- 2. 域索引 ----
    # ⛔ 2026-10-07 瘦身: §2 原来是"每条带 100+ 字描述", 占全文件 72%(130 行/15212 字符),
    #    每轮全量注入白烧。_recall.py 不读 MEMORY.md(它直接 digest 记忆文件), 所以这里
    #    只需要"slug 目录" —— 关键词命中哪个 slug, 就 Read 那个文件看 frontmatter description。
    #    --full 可以退回带描述的旧版(写到 MEMORY.full.md, 不覆盖 MEMORY.md)。
    A("## 2. 全量索引（按域，只列 slug）")
    A("")
    A("> 描述在各记忆文件的 frontmatter 里，这里只给路径。要判断相关性就直接 Read 那个文件。")
    A("")
    for dom, slugs in reg["domains"].items():
        real = [s for s in slugs if s in have or s in descs]
        if not real:
            continue
        A("### %s（%d）" % (dom, len(real)))
        # 每行最多 ~180 字符, 超了就换行
        buf, out_lines = [], []
        for s in real:
            piece = "`%s`" % s
            if len(" ".join(buf + [piece])) > 215:
                out_lines.append(" ".join(buf))
                buf = [piece]
            else:
                buf.append(piece)
        if buf:
            out_lines.append(" ".join(buf))
        for l in out_lines:
            A("- " + l)
        A("")

    # ---- 3. 孤儿与死链 ----
    orphans = sorted(have - used)
    # 死链只查"真实记忆文件"这条线; 主键是短名, 不该按文件判
    known = have | set(primary_files.keys()) | set(primary_files.values())
    dead = sorted(s for s in used if s not in known)
    A("## 3. 完整性检查")
    A("")
    if orphans:
        A("- ⚠️ **孤儿记忆**（有文件但没进任何域 = 永久失联）：")
        for s in orphans:
            A("  - `%s` — %s" % (s, descs.get(s) or read_frontmatter_desc(s) or "(无说明)"))
    else:
        A("- ✅ 无孤儿记忆")
    if dead:
        A("- ⛔ **死链**（索引里有但文件没了）：%s" % ", ".join("`%s`" % s for s in dead))
    else:
        A("- ✅ 无死链")
    A("- 记忆文件 %d 个 / 主键 %d 个 / 域 %d 个" % (len(have), len(reg["active"]), len(reg["domains"])))
    A("")

    # ---- 4. 日志表 ----
    # ⛔ 这张表是 _memlog.py 渲染的, 别手填 —— 手填的下次跑 _gen_index.py 就没了。
    #    全量(含筛序)看仪表板「📜 日志」或 `python _memlog.py list`。
    A("## 4. 日志表")
    A("")
    A("> 记忆库的**过程**流水（A=操作 B=会话），最近 %d 条，全量见 `_memlog.py list`。" % LOG_ROWS)
    A("")
    rows = _memlog.read(limit=LOG_ROWS)
    if not rows:
        A("- （还没记过）")
    else:
        A("| 时间 | 类 | 动作 | 对象 | 说明 |")
        A("|---|---|---|---|---|")
        for r in rows:
            A("| %s | %s | %s | %s | %s |" % (
                _cell(r.get("ts", ""))[5:16],
                "A" if r.get("kind") == "op" else "B",
                _cell(_memlog.label(r)) + ("" if r.get("ok", True) else " ✗"),
                _cell(r.get("obj", "")),
                _cell(r.get("detail", "")),
            ))
    A("")
    return "\n".join(out)


def _cell(s):
    """markdown 表格单元: 竖线和换行会把表冲垮。"""
    return str(s or "").replace("|", "/").replace("\n", " ").strip()


def main():
    reg = read_registry()
    # 先记账再渲染：这一条会出现在本次生成的日志表里（dry-run 不记账）。
    if "--dry-run" not in sys.argv:
        _memlog.log("op", "regen_index", "MEMORY.md",
                    "%d 主键 / %d 域" % (len(reg["active"]), len(reg["domains"])),
                    src="_gen_index.py")
    text = build(reg)
    if "--dry-run" in sys.argv:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)
        return
    io.open(OUT, "w", encoding="utf-8").write(text)
    print("已重写 %s (%d 字符)" % (OUT, len(text)))


if __name__ == "__main__":
    main()