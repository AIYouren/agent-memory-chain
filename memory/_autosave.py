#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stop hook —— 自动把本轮结论写进冷库(保守档: 只写冷库, 不晋升热库)。

链 id 来源(按优先级):
  1. .current-chain  —— _recall.py(UserPromptSubmit) 本轮写下的
  2. 兜底: 自己读最新 transcript 的最后一条用户输入现算一遍

⛔ 纯 stdlib、不调模型 = 零 token 成本。hook 永不打断会话(全 try)。
⛔ 防灌水: 同一 session + 同一 topic 只写一次; 空内容跳过。

跑法(手动自测):
  PYTHONUTF8=1 python _autosave.py
"""
import io
import json
import os
import re
import sys
import time
import importlib.util as _ilu

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.expanduser("~/.deep-memory/cold-notes/raw.jsonl")
WRITE_COLD = os.path.expanduser(
    "~/.claude/skills/chroma-hybrid-search/scripts/write_cold.py")
STATE = os.path.join(HERE, ".autosave-state.json")


def _cr():
    spec = _ilu.spec_from_file_location("_chain_resolve", os.path.join(HERE, "_chain_resolve.py"))
    m = _ilu.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def read_stdin_json():
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def load_state():
    try:
        return json.load(io.open(STATE, encoding="utf-8"))
    except Exception:
        return {}


def save_state(s):
    try:
        with io.open(STATE, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False)
    except Exception:
        pass


def clean(text):
    """去掉 markdown 装饰, 压成一行摘要。"""
    t = re.sub(r"[`*#>\[\]()!]", "", text)
    t = re.sub(r"\s+", " ", t).strip()
    return t


# ---- B 类日志: 这一轮会话干了什么 ----
MEMLOG_TOUCH_WINDOW = 600          # 认定「本轮动过」的 mtime 窗口(秒)


def touched_memory_files():
    """最近动过的记忆 .md。⛔ 只认 mtime, 不知道是谁改的 —— 同机多开会话会串,
    本机基本单会话, 可接受。MEMORY.md 排除: 它是 _gen_index.py 刷出来的,
    另有 regen_index 记账, 混进来会让每轮都像改了记忆。"""
    try:
        now = time.time()
        out = []
        for fn in sorted(os.listdir(HERE)):
            if not fn.endswith(".md") or fn == "MEMORY.md" or fn.startswith("."):
                continue
            p = os.path.join(HERE, fn)
            try:
                if now - os.path.getmtime(p) <= MEMLOG_TOUCH_WINDOW:
                    out.append(fn)
            except OSError:
                continue
        return out
    except Exception:
        return []


def _log_session(session, chain, topic, content, touched):
    try:
        import _memlog
        _memlog.log("session", "round", chain or "unfiled",
                    (topic or "")[:70] + ((" ｜ 动过: " + ", ".join(touched)) if touched else ""),
                    ok=True, src="_autosave.py", session=session)
    except Exception:
        pass


def main():
    dry = "--dry-run" in sys.argv
    cr = _cr()
    payload = read_stdin_json()
    session = str(payload.get("session_id") or payload.get("sessionId") or "")

    path = cr.newest_transcript()
    if not path:
        return

    chain = cr.current_chain(session)
    if not chain:
        chain = cr.match_chain(cr.last_user_prompt(path)) or cr.UNFILED

    prompt = cr.last_user_prompt(path)
    answer = cr.last_assistant_text(path)
    if not (prompt or answer):
        return

    topic = clean(prompt)[:60] or "自动记录"
    content = ("用户: %s\n助手: %s" % (clean(prompt), clean(answer)))[:1500]
    touched = touched_memory_files()
    # 防灌水: 保守档只收有实质内容的轮次。
    # ⛔ 门槛原本是 6/80, 实测放进来的全是「先存着明天弄」「不能加名单？」这种碎话 ——
    #    autosave 抽不了要点(零 token), 只能靠门槛挡; 它落的条目已按 tag=autosave
    #    在仪表板侧全部剔除(见 _chain_dash.py 的 split_chatlog), 这里再抬一道。
    substantial = len(topic) >= 12 and len(content) >= 200

    st = load_state()

    # B 类日志: 这一轮会话干了什么。判定比冷库松一档 —— 「动过记忆文件」的轮次
    # 话再短也该进日志表, 那才是记忆库的真动作; 纯客套话(touched 空 + 不 substantial)不记。
    logkey = session + "|" + topic + "|" + ",".join(touched)
    if (substantial or touched) and st.get("log_key") != logkey and not dry:
        _log_session(session, chain, topic, content, touched)
        st["log_key"] = logkey
        save_state(st)

    if not substantial:
        return

    # 防灌水: 同一 session 同一 topic 只写一次
    key = session + "|" + topic
    if st.get("last_key") == key:
        return

    if not os.path.exists(WRITE_COLD):
        return
    if dry:
        print("[dry-run] chain=%s topic=%s" % (chain, topic))
        print("[dry-run] content=%s" % content[:200])
        return
    import subprocess
    cmd = [sys.executable, WRITE_COLD,
           "--project", chain or cr.UNFILED,
           "--topic", topic,
           "--content", content,
           "--tags", "autosave",
           "--skill", "deep-memory",
           "--memory-type", "knowledge"]
    try:
        subprocess.run(cmd, capture_output=True, timeout=20)
    except Exception:
        return

    st["last_key"] = key
    st["last_chain"] = chain
    st["last_ts"] = __import__("time").strftime("%Y-%m-%d %H:%M:%S")
    save_state(st)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # hook 永不打断会话
