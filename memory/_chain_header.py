#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""链头文件生成器 (2026-10-12)

干什么: 给每条链的工作目录写一份 CLAUDE.md(链头文件) —— 该链的专属规矩/资产/下一步,
        全局 CLAUDE.md 只留通用条, 专属的全下沉到这里。
怎么做: 读 _registry.json 的 active 链卡; 首次运行给缺 rules 的链补 rules 字段;
        按工作目录分组(两条链可以共用同一个工作目录, 合成一个文件);
        写 <work>/CLAUDE.md, 带自动生成标记, 不覆盖手写文件(先备份)。
跑法:   PYTHONUTF8=1 python _chain_header.py [--dry-run]
"""
import io
import json
import os
import re
import sys
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
REG = os.path.join(HERE, "_registry.json")
MARK = "<!-- chain-header:auto -->"

# 硬约束种子: 从各链现有 next/status + MEMORY.md §1 提炼。缺的留空, 用户可补。
RULES = {
    "demo-api-project": [
        "跑测试前先起本地服务，端口写在 .env 里，别写死在代码里",
        "对外接口改了必须同步 README 的参数表，否则下次一定漏",
    ],
    "demo-docs-project": [
        "出稿先给用户改一遍再发布，别直接发",
        "配图用无版权图，出所用图注标来源",
    ],
}


def clean_work(w):
    """work 字段可能带括号说明, 只取路径部分。"""
    if not w:
        return ""
    w = re.split(r"\s*\(", w, 1)[0].strip()
    return w.rstrip("\\/")


def load_reg():
    return json.load(io.open(REG, encoding="utf-8"))


def seed_rules(reg):
    """给缺 rules 的链补 rules。返回是否改动。"""
    changed = False
    for a in reg["active"]:
        if "rules" not in a:
            a["rules"] = RULES.get(a["id"], [])
            changed = True
    return changed


def build_header(chains):
    """chains: 同一目录下的若干链卡。合成一份 markdown。"""
    out = [MARK, ""]
    titles = " / ".join(c.get("title", c["id"]) for c in chains)
    out.append("# %s —— 链头文件" % titles)
    out.append("")
    out.append("> 本文件由 home 记忆目录的 `_chain_header.py` 从 `_registry.json` 生成，**别手改**；")
    out.append("> 改规矩去改 `_registry.json` 的 `rules`，再跑 `PYTHONUTF8=1 python _chain_header.py`。")
    out.append("> 全局通用规矩在 `~/.claude/CLAUDE.md`；本条链的记忆条目见仪表板「🔗 记忆链」区块。")
    out.append("")
    for c in chains:
        out.append("## %s" % c.get("title", c["id"]))
        out.append("")
        out.append("- **链 id**：`%s`" % c["id"])
        if c.get("status"):
            out.append("- **状态**：%s" % c["status"])
        if c.get("deliverable"):
            out.append("- **成品**：%s" % c["deliverable"])
        if c.get("readme"):
            out.append("- **开工先读**：`%s`" % c["readme"])
        if c.get("work"):
            out.append("- **目录**：`%s`" % c["work"])
        if c.get("scripts"):
            out.append("- **脚本/能力**：`%s`" % c["scripts"])
        rules = c.get("rules") or []
        if rules:
            out.append("")
            out.append("**硬约束（本条链专属）**")
            out.append("")
            for r in rules:
                out.append("- %s" % r)
        if c.get("blocker"):
            out.append("")
            out.append("- ⛔ **卡点**：%s" % c["blocker"])
        if c.get("next"):
            out.append("")
            out.append("**下一步**：%s" % c["next"])
        out.append("")
    return "\n".join(out)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    dry = "--dry-run" in sys.argv
    reg = load_reg()
    changed = seed_rules(reg)
    if changed and not dry:
        io.open(REG, "w", encoding="utf-8").write(
            json.dumps(reg, ensure_ascii=False, indent=1))

    # 按工作目录分组
    groups = OrderedDict()
    for a in reg["active"]:
        w = clean_work(a.get("work", ""))
        if not w:
            print("  skip (无 work): %s" % a["id"])
            continue
        groups.setdefault(w, []).append(a)

    for w, chains in groups.items():
        if not os.path.isdir(w):
            print("  skip (目录不存在): %s" % w)
            continue
        target = os.path.join(w, "CLAUDE.md")
        text = build_header(chains)
        if dry:
            print("=== [dry] %s (%d 链) ===" % (target, len(chains)))
            print(text[:400])
            continue
        if os.path.exists(target):
            old = io.open(target, encoding="utf-8", errors="replace").read()
            if MARK not in old:
                bak = target + ".bak-20261012"
                io.open(bak, "w", encoding="utf-8").write(old)
                print("  已备份手写文件 -> %s" % bak)
        io.open(target, "w", encoding="utf-8").write(text)
        print("  wrote %s (%d 链: %s)" % (target, len(chains),
                                          ", ".join(c["id"] for c in chains)))
    if changed:
        print("已给 %s 补 rules 字段" % REG)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
