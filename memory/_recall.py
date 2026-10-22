#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
UserPromptSubmit hook —— 记忆自动召回。

干什么: 拿你这句话去匹配 _registry.json 的别名/slug/标题, 命中的记忆
        摘要(不是全文)直接注入上下文, 省得我在 105 条记忆里盲扫。

输出: JSON, hookSpecificOutput.additionalContext
不干: 不改文件、不联网、不写库。纯读 + 打印, 失败就静默退出。

⛔ 成本纪律: 注入的是**摘要**(状态/下一步/关键坑前若干行), 不是全文。
   全文平均 15KB, 三篇就 45KB —— 那等于没省。要细节我再去 Read 正文。

跑法(手动自测): PYTHONUTF8=1 python _recall.py "剪辑产品怎么样了"
"""

import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REG = os.path.join(HERE, "_registry.json")

MAX_HITS = 3          # 最多召回几条
MAX_LINES = 22        # 每条最多摘几行
MAX_CHARS = 2600      # 整块注入上限
MIN_SCORE = 3         # 低于这个分不召回(防"帮我看看"这种触发一片)

# 这些词到处都有, 命中不算数
STOP = set(
    """的 了 是 在 和 与 我 你 他 它 这 那 有 没 不 也 就 都 而 及 或 一个 一下 怎么
    什么 哪些 哪个 为什么 怎样 如何 可以 能否 需要 应该 现在 今天 昨天 明天 继续
    开始 结束 完成 好了 看看 读读 帮我 请 麻烦 谢谢 一下 这个 那个 现在 还有
    能不能 是不是 应该 怎么 为什么 什么 情况 问题 事情 东西 时候 直接 这样 那样
    的话 可能 感觉 觉得 知道 想要 需要 打算 准备 弄 做 去 来 上 下 里 中""".split()
)


_LAST_SESSION = ""


def read_prompt():
    """hook 走 stdin(JSON), 手动跑走 argv。顺带记下 session_id。"""
    global _LAST_SESSION
    if len(sys.argv) > 1:
        return " ".join(sys.argv[1:])
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return ""
        data = json.loads(raw)
        _LAST_SESSION = str(data.get("session_id") or data.get("sessionId") or "")
        # Claude Code 的 UserPromptSubmit payload 里 prompt 字段可能叫 prompt
        return str(data.get("prompt") or data.get("user_prompt") or "")
    except Exception:
        return ""


def load_registry():
    try:
        return json.load(io.open(REG, encoding="utf-8"))
    except Exception:
        return None


def tokens(text):
    """中英混排切词: 中文按 2-gram + 英文按单词。"""
    t = text.lower()
    out = set(re.findall(r"[a-z0-9_\-]{2,}", t))
    han = re.findall(r"[一-鿿]+", t)
    for seg in han:
        if len(seg) == 1:
            out.add(seg)
        for i in range(len(seg) - 1):
            out.add(seg[i : i + 2])
    return out


def score(prompt, text, weight):
    """字面命中才算分。

    ⛔ 踩过的坑: 早先版本用 2-gram token 交集, 结果"产品""产""品"这类
    碎片到处命中, 每个别名白送 40-108 分, 八条全被召回。**必须按字面
    子串判断**——提示里真的出现了这个叫法, 才算命中。
    """
    s = 0.0
    low = prompt.lower()
    t = text.lower()
    if t and t in low:                       # 整个叫法出现 = 最强信号
        s += weight * 5.0
    for phrase in re.split(r"[,\s、/]+", t):
        p = phrase.strip()
        if len(p) >= 2 and p in low:         # 分词后仍命中
            s += weight * 3.0
    return s


def digest(slug, limit=MAX_LINES):
    """从记忆正文里摘最有信息量的前若干行(跳过 frontmatter)。"""
    path = os.path.join(HERE, slug + ".md")
    if not os.path.exists(path):
        return None
    lines = io.open(path, encoding="utf-8", errors="replace").read().splitlines()
    body, in_fm, kept = [], False, 0
    for ln in lines:
        if ln.strip() == "---":
            in_fm = not in_fm
            continue
        if in_fm:
            continue
        if not ln.strip():
            continue
        body.append(ln)
        kept += 1
        if kept >= limit:
            break
    if not body:
        return None
    return "\n".join(body)


def have_cache(reg):
    try:
        return {f[:-3] for f in os.listdir(HERE) if f.endswith(".md") and f != "MEMORY.md"}
    except Exception:
        return set()


def build_context(reg, prompt):
    pl = prompt.lower()
    cands = []

    for a in reg.get("active", []):
        s = 0.0
        s += score(pl, a["title"], 3.0)
        for al in a.get("aliases", []):
            s += score(pl, al, 4.0)
        if s >= MIN_SCORE:
            cands.append((s, a))

    # 别名补充(alias_extras): 不在 active 里但你会这么叫的记忆
    for al, targets in reg.get("alias_extras", {}).items():
        if al.startswith("_"):
            continue
        s2 = score(pl, al, 4.0)
        if s2 <= 0:
            continue
        # 第一个目标是 slug, 其余当显示文本
        slugs = [t.strip() for t in targets.split("/")]
        for sl in slugs:
            sl = sl.strip().strip("`")
            if sl in have_cache(reg):
                cands.append((s2, {"title": al + " → " + sl, "id": sl, "file": sl,
                                   "_extra": True}))

    # 全量域: 主键没命中时, 看是不是提到了某个域里的记忆
    if not cands:
        for dom, slugs in reg.get("domains", {}).items():
            s = score(pl, dom, 2.0)
            if s > MIN_SCORE:
                cands.append((s * 0.5, {"title": dom, "id": dom, "_dom": True}))

    cands.sort(key=lambda x: -x[0])
    if not cands or cands[0][0] < MIN_SCORE:
        # 兜底: 问的是"做到哪了/昨天/成品"这类, 没点名项目
        meta = score(pl, "昨天 今天 成品 做完 做到哪 继续 进度 怎么样了 状态", 1.0)
        if meta < MIN_SCORE:
            return None
        rows = []
        for a in reg.get("active", []):
            d = a.get("deliverable") or a.get("work") or ""
            rows.append("- **%s** `%s` — %s%s" % (
                a["title"], a["id"], a.get("status", "—"),
                ("｜" + d) if d else ""))
        head = (
            "## 🧠 记忆召回 · 没点名项目，按台账在跑的活列一遍"
            "（主键表 `_registry.json`；点名任一项我再展开细节）\n\n"
        )
        return (head + "\n".join(rows))[:MAX_CHARS]
    top = cands[0][0]
    # 相对阈值: 第二名不到第一名的一半就丢掉, 防止长尾噪音
    hits = [c for c in cands[:MAX_HITS] if c[0] >= max(MIN_SCORE, top * 0.5)]
    if not hits:
        return None

    out = ["## 🧠 记忆召回（_recall.py 自动匹配，与你说的话相关）", ""]
    for s, a in hits:
        if a.get("_dom"):
            out.append("**%s**（域）— 相关记忆见 MEMORY.md §2「%s」" % (a["title"], a["title"]))
            out.append("")
            continue
        out.append("### %s  `主键 %s`" % (a["title"], a["id"]))
        if a.get("_extra"):
            out.append("- 记忆文件：`%s.md`（细节自己 Read）" % a["file"])
            out.append("")
            continue
        if a.get("status"):
            out.append("- 状态：%s" % a["status"])
        if a.get("next"):
            out.append("- 下一步：%s" % a["next"])
        if a.get("blocker"):
            out.append("- ⛔ 卡点：%s" % a["blocker"])
        if a.get("work"):
            out.append("- 目录：`%s`" % a["work"])
        if a.get("deliverable"):
            out.append("- 现有成品：%s" % a["deliverable"])
        slug = a.get("file", a["id"])
        d = digest(slug)
        if d:
            out.append("- 记忆摘录（`%s.md`，要全文我再读）：" % slug)
            for ln in d.splitlines()[:8]:
                out.append("  > " + ln[:200])
        out.append("")

    text = "\n".join(out)
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n…（已截断，要细节直接 Read 对应 .md）"
    return text


def main():
    prompt = read_prompt()
    if not prompt.strip():
        return
    reg = load_registry()
    if not reg:
        return

    # 本轮命中的链 id 落盘给 Stop 时的 _autosave.py 用(每轮覆盖; 按 session 分文件防并发覆盖)
    try:
        import importlib.util as _ilu
        spec = _ilu.spec_from_file_location(
            "_chain_resolve", os.path.join(HERE, "_chain_resolve.py"))
        cr = _ilu.module_from_spec(spec)
        spec.loader.exec_module(cr)
        cr.write_current_chain(cr.match_chain(prompt, reg) or cr.UNFILED, _LAST_SESSION)
    except Exception:
        pass

    ctx = build_context(reg, prompt)
    if not ctx:
        return
    sys.stdout.reconfigure(encoding="utf-8")
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": ctx,
                }
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # hook 永不打断会话