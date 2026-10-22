#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
冷库 project 字段迁移 —— 把 cwd 目录名(如 'your-home-dir')重判成「链 id / 主题域」。

背景(10-12 实测): raw.jsonl 里 331 条 project='your-home-dir'(write_cold.py 取 cwd 目录名,
会话都从 C:\\Users\\YOU 起), search.py --project <链id> 第一趟抓不到东西。

三级判定(先严后松, 越靠前越准):
  1. **链 id**    —— 正文命中链 id/别名/work 目录名/slug(标题命中算强信号)
  2. **主题域**   —— 关键词表**运行时读** ~/.deep-memory 知识库分类索引, 不复制(复制必漂)
  3. **skill 名** —— 落到兜底前最后一层; ⛔ deep-memory/general 是 write_cold 的兜底值,
                    不代表内容主题(实测「[deep-memory] 四六级成绩查询报错」), 已排除
  都不中 → unfiled(宁缺勿滥; search.py 抓不到会走全库兜底, 不会丢)

⛔ 已是合法链 id 的**一律不动** —— 那是 autosave 从 .current-chain 取的会话真值, 比正文猜的准。
   本脚本只补 unfiled / 旧 cwd 目录名两个窟窿。只改 project 一个字段, 幂等。

跑法:
  PYTHONUTF8=1 python _fix_project.py --dry-run   # 只看分布
  PYTHONUTF8=1 python _fix_project.py             # 落盘(先自己 cp 一份备份!)
  # 落盘后刷新向量元数据:
  ~/.deep-memory/.venv/Scripts/python.exe ../../../skills/chroma-hybrid-search/scripts/update_db.py
"""
import argparse
import io
import json
import os
import re
import shutil
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REG = os.path.join(HERE, "_registry.json")
RAW = os.path.expanduser("~/.deep-memory/cold-notes/raw.jsonl")

# cwd 目录名 -> 链 id (write_cold.py 记下来的旧 project 值)
CWD_MAP = {
    "demo-api-work": "demo-api-project",
    "api-work": "demo-api-project",
    "docs-work": "demo-docs-project",
}


def load_registry():
    return json.load(io.open(REG, encoding="utf-8"))


def build_matchers(reg):
    """每链 -> (id, [patterns]) ; patterns 含 id / 别名 / work 目录名 / file slug。"""
    out = []
    for a in reg.get("active", []):
        cid = a["id"]
        VALID_IDS.add(cid)
        pats = {cid}
        for al in a.get("aliases", []):
            pats.add(al)
        for k in ("work", "scripts"):
            v = a.get(k) or ""
            base = os.path.basename(v.rstrip("\\/"))
            if base:
                pats.add(base)
        if a.get("file"):
            pats.add(a["file"])
        out.append((cid, sorted(pats, key=len, reverse=True)))
    return out


def hit(text_low, pat):
    """中文子串 / 英文词边界(短词防误伤)。"""
    p = pat.lower()
    if not p:
        return False
    if p.isascii() and len(p) <= 3:
        return re.search(r"(?<![a-z0-9])" + re.escape(p) + r"(?![a-z0-9])", text_low) is not None
    return p in text_low


# 标题里出现才算强信号；正文里顺带提一嘴的通用词(标注/选型/延迟)不算
STRONG = 4.0     # 标题命中
WEAK = 1.0       # 正文/标签/skill 命中
ASSIGN_AT = 4.0  # 达不到就当 unfiled(宁缺勿滥, 漏了 search 会走跨库兜底)
# 太泛的别名: 任何链的正文里都可能出现, 不足以判定归属
IGNORE_ALIASES = {"选型", "延迟"}
VALID_IDS = set()  # build_matchers 填; classify 用来保幂等

# ---- 二级: 主题域(不属任何链、但属某个主题区的旧活) ----
# 关键词表**运行时从 deep-memory 知识库的分类索引读**, 不在这儿复制一份(复制必漂)。
KB_INDEX = os.path.expanduser("~/.deep-memory/knowledge-base/_index.json")
AREA_AT = 4.0    # 主题域阈值(比链松: 域是归类不是归属, 错一点无伤)
# ⛔ 太泛的分类: 关键词是 api/claude/code 这种, 会吞掉全部条目
AREA_EXCLUDE = {"imported-claude-memory", "user-profile"}
AREA_IDS = set()  # load_areas 填; classify 用来保幂等
# ⛔ write_cold 的兜底 skill 值 —— 不表示内容主题, 不能当主题域用
IGNORE_SKILLS = {"", "deep-memory", "general", "none", "null", "other"}


def load_areas():
    """deep-memory 知识库分类 -> [(id, [关键词...])]。文件不在就返回空 = 退回全 unfiled。"""
    if not os.path.exists(KB_INDEX):
        return []
    kb = json.load(io.open(KB_INDEX, encoding="utf-8"))
    out = []
    for c in kb.get("categories", []):
        cid = c.get("id")
        kws = [k for k in (c.get("keywords") or []) if k]
        if cid and kws and cid not in AREA_EXCLUDE:
            out.append((cid, sorted(kws, key=len, reverse=True)))
    return out


def classify_area(topic, rest, areas):
    """归主题域。标题命中算 4 分, 正文/标签/skill 命中算 1 分, 达不到 AREA_AT 返回 None。"""
    best, best_score = None, 0.0
    for cid, kws in areas:
        s = 0.0
        for k in kws:
            kl = k.lower()
            if len(kl) < 2:      # 单字关键词(「题」这种)太松, 直接不要
                continue
            if hit(topic, kl):
                s += 4.0
            elif hit(rest, kl):
                s += 1.0
        if s > best_score:
            best, best_score = cid, s
    return best if best_score >= AREA_AT else None


def classify(entry, matchers, areas=()):
    topic = str(entry.get("topic", "")).lower()
    rest = " ".join([
        str(entry.get("content", "")),
        " ".join(entry.get("tags") or []),
        str(entry.get("skill", "")),
    ]).lower()

    # ⛔ 已有合法链 id 就直接保留: 那是写这条时 autosave 从 .current-chain 取的**会话真值**,
    # 比我按正文猜的准。本脚本只补 unfiled / 旧 cwd 目录名 这两个窟窿, 不做覆盖。
    old = str(entry.get("project", ""))
    if old in VALID_IDS:
        return old

    best, best_score = "unfiled", 0.0
    for cid, pats in matchers:
        s = 0.0
        for p in pats:
            if p in IGNORE_ALIASES:
                continue
            w = STRONG if p.lower() == cid.lower() else WEAK
            if hit(topic, p):
                s += w * 4.0
            elif hit(rest, p):
                s += w
        if s > best_score:
            best, best_score = cid, s

    if best_score < ASSIGN_AT:
        best = "unfiled"
    # 旧 project 值(cwd 目录名, 如 'your-home-dir')是强信号: 压过正文里顺带提一嘴
    if best_score < ASSIGN_AT and old in CWD_MAP:
        best = CWD_MAP[old]
    # 归不到链 → 试主题域; 域也认不出就留 unfiled(检索会走全库兜底, 不会丢)
    if best == "unfiled":
        area = classify_area(topic, rest, areas)
        if area:
            best = area
        elif old in AREA_IDS:
            best = old      # 幂等: 已是合法主题域且这轮没更强证据, 保留
    # 最后兜一层: 具体 skill 名。⛔ deep-memory/general 是 write_cold 的**兜底值**,
    # 不代表内容属于该主题(实测「[deep-memory] 四六级成绩查询报错」), 必须排除。
    if best == "unfiled":
        s = str(entry.get("skill") or "").strip().lower()
        if s and s not in IGNORE_SKILLS:
            best = s
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--raw", default=RAW)
    args = ap.parse_args()

    reg = load_registry()
    matchers = build_matchers(reg)
    areas = load_areas()
    AREA_IDS.update(cid for cid, _ in areas)
    print("链 %d 条 / 主题域 %d 个" % (len(matchers), len(areas)))

    lines = [l for l in io.open(args.raw, encoding="utf-8").read().splitlines() if l.strip()]
    new_lines, dist = [], {}
    changed = 0
    for l in lines:
        e = json.loads(l)
        nid = classify(e, matchers, areas)
        if e.get("project") != nid:
            changed += 1
        e["project"] = nid
        dist[nid] = dist.get(nid, 0) + 1
        new_lines.append(json.dumps(e, ensure_ascii=False))

    print("total %d  changed %d" % (len(lines), changed))
    for k, v in sorted(dist.items(), key=lambda x: -x[1]):
        print("  %-28s %d" % (k, v))

    if args.dry_run:
        print("\n[dry-run] 未落盘")
        return

    bak = args.raw + ".bak-20261013-projfix"
    if not os.path.exists(bak):
        shutil.copy2(args.raw, bak)
        print("备份 ->", bak)
    else:
        print("备份已存在, 跳过:", bak)
    with io.open(args.raw, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(new_lines) + "\n")
    print("已写回", args.raw, time.strftime("%H:%M:%S"))


if __name__ == "__main__":
    main()
