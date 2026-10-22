#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""记忆库日志表（2026-10-22）—— A 操作流水 + B 会话流水，两条河汇进一张表。

干什么: 记忆库以前只有**结果**(raw.jsonl 上盖 kept_at/dropped_at、_registry.json 的一堆 .bak),
        没有**过程**: 谁、什么时候、动了哪一条、成没成。这张表补的就是过程。

数据:   _memlog.jsonl —— 追加写, 一行一条, 永不原地改(要更正就再写一条)。
        ⛔ 不要改成"读全量-改-写回", 那样两个写方会互相覆盖; 追加写是唯一安全口径。

字段:
  ts       "2026-10-22 14:30:01"
  kind     "op"      = A 类: 记忆库本体被改动(staging 的 keep/drop/归档/捞回、重建索引、
                       仪表板里改/删记忆、整库 regen)
           "session" = B 类: 一轮会话干了什么(哪条链、聊了什么、动了哪些记忆文件)
  act      动作短名, 见 ACT_LABEL
  obj      对象(链 slug / 条目 id / 文件名), 可空
  detail   人话说明, 可空
  ok       成没成(失败也记, 失败的行才是排障要看的)
  src      谁写的这条日志(_staging.py / _autosave.py / ...)
  session  会话 id, 可空

跑法:
  PYTHONUTF8=1 python _memlog.py list [--kind op|session] [--limit 20] [--json]
  PYTHONUTF8=1 python _memlog.py stats
纯标准库。任何写方都不许因为它挂掉而中断主流程 —— log() 全吞异常。
"""
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "_memlog.jsonl")

KINDS = ("op", "session")
ACT_LABEL = {
    "keep": "晋升入正式库",
    "drop": "判无用",
    "archive": "归档",
    "restore": "从归档捞回",
    "migrate": "补齐字段",
    "regen_index": "重建 MEMORY.md",
    "regen_all": "整库重跑三脚本",
    "mem_save": "改记忆文件",
    "mem_delete": "删记忆文件",
    "round": "一轮会话",
}


def _ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(kind, act, obj="", detail="", ok=True, src="", session=""):
    """追加一条。永不抛 —— 日志不能把主流程带崩。"""
    try:
        if kind not in KINDS:
            kind = "op"
        row = {
            "ts": _ts(),
            "kind": kind,
            "act": str(act or ""),
            "obj": str(obj or "").replace("\n", " ")[:120],
            "detail": str(detail or "").replace("\n", " ")[:300],
            "ok": bool(ok),
            "src": str(src or ""),
            "session": str(session or "")[:40],
        }
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return None


def read(kind=None, limit=None):
    """按时间倒序返回。坏行跳过(不许一行坏数据炸掉整张表)。"""
    if not os.path.exists(LOG):
        return []
    out = []
    for line in open(LOG, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if not isinstance(r, dict):
            continue
        if kind and r.get("kind") != kind:
            continue
        out.append(r)
    out.reverse()
    return out[:limit] if limit else out


def label(row):
    return ACT_LABEL.get(row.get("act", ""), row.get("act", ""))


def cmd_list(a):
    rows = read(kind=a.kind or None, limit=a.limit)
    if a.json:
        sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps({"ok": True, "total": len(rows), "items": rows},
                         ensure_ascii=False))
        return 0
    sys.stdout.reconfigure(encoding="utf-8")
    if not rows:
        print("（空）")
        return 0
    for r in rows:
        mark = " " if r.get("ok", True) else "✗"
        print("%s %s  %-7s %-14s %-22s %s" % (
            r.get("ts", ""), mark, r.get("kind", ""), r.get("act", ""),
            (r.get("obj") or "")[:22], (r.get("detail") or "")[:60]))
    return 0


def cmd_stats(_a):
    rows = read()
    by_kind, by_act = {}, {}
    for r in rows:
        by_kind[r.get("kind", "?")] = by_kind.get(r.get("kind", "?"), 0) + 1
        by_act[r.get("act", "?")] = by_act.get(r.get("act", "?"), 0) + 1
    sys.stdout.reconfigure(encoding="utf-8")
    print("日志共 %d 条" % len(rows))
    for k, v in sorted(by_kind.items(), key=lambda x: -x[1]):
        print("  kind=%-8s %d" % (k, v))
    for k, v in sorted(by_act.items(), key=lambda x: -x[1]):
        print("  act=%-14s %d" % (k, v))
    bad = sum(1 for r in rows if not r.get("ok", True))
    print("  失败 %d 条" % bad)
    return 0


def main():
    import argparse
    p = argparse.ArgumentParser(description="记忆库日志表")
    sub = p.add_subparsers(dest="cmd")
    pl = sub.add_parser("list")
    pl.add_argument("--kind", choices=list(KINDS), default="")
    pl.add_argument("--limit", type=int, default=20)
    pl.add_argument("--json", action="store_true")
    ps = sub.add_parser("stats")
    a = p.parse_args()
    if a.cmd == "stats":
        return cmd_stats(a)
    return cmd_list(a)


if __name__ == "__main__":
    raise SystemExit(main())
