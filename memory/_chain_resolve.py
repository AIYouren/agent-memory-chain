#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
链解析共享模块 —— 给 _recall.py / _autosave.py 用。

干什么: 从「最新 transcript 里的最后一条真实用户输入」匹配 _registry.json,
        得出本轮属于哪条链, 供 autosave 决定 write_cold.py --project <链id>。
不干: 不写冷库、不联网。纯读 + 可选写 .current-chain。

⛔ 为什么不直接用 cwd: 会话都从 C:\\Users\\YOU 起, cwd 恒为 'your-home-dir'
   (这正是 10-12 冷库 project 字段全废的原因)。必须从 prompt 判链。
"""
import glob
import io
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REG = os.path.join(HERE, "_registry.json")
CHAIN_FILE = os.path.join(HERE, ".current-chain")
# transcript 目录 = memory 目录的上一级(.../projects/C--Users-YOU)
PROJ_DIR = os.path.dirname(HERE)
UNFILED = "unfiled"

import importlib.util as _ilu

_r = None


def _recall_mod():
    global _r
    if _r is None:
        spec = _ilu.spec_from_file_location("_recall", os.path.join(HERE, "_recall.py"))
        m = _ilu.module_from_spec(spec)
        spec.loader.exec_module(m)
        _r = m
    return _r


def load_registry():
    return json.load(io.open(REG, encoding="utf-8"))


def match_chain(prompt, reg=None):
    """返回命中的链 id; 没命中返回 None。复用 _recall 的字面匹配打分。"""
    if not prompt or not prompt.strip():
        return None
    r = _recall_mod()
    reg = reg or load_registry()
    pl = prompt.lower()
    best, best_score = None, 0.0
    for a in reg.get("active", []):
        s = r.score(pl, a["title"], 3.0)
        for al in a.get("aliases", []):
            s += r.score(pl, al, 4.0)
        if s > best_score:
            best, best_score = a["id"], s
    if best_score < r.MIN_SCORE:
        return None
    return best


def newest_transcript():
    files = glob.glob(os.path.join(PROJ_DIR, "*.jsonl"))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def _text_of(blocks):
    if isinstance(blocks, str):
        return blocks
    if not isinstance(blocks, list):
        return ""
    out = []
    for b in blocks:
        if isinstance(b, dict) and b.get("type") == "text":
            out.append(b.get("text", ""))
    return "\n".join(out)


def last_user_prompt(path):
    """从 transcript 尾部找最后一条真实用户输入(排除 tool_result / 系统注入)。"""
    try:
        lines = io.open(path, encoding="utf-8", errors="replace").read().splitlines()
    except Exception:
        return ""
    for ln in reversed(lines[-400:]):
        if not ln.strip():
            continue
        try:
            d = json.loads(ln)
        except Exception:
            continue
        if d.get("type") != "user":
            continue
        c = (d.get("message") or {}).get("content")
        if isinstance(c, list):
            if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
                continue
            t = _text_of(c)
        else:
            t = c or ""
        t = (t or "").strip()
        # 跳过 hook 注入 / 系统提醒 这类非人话
        if not t or t.startswith("<") or "system-reminder" in t[:200]:
            continue
        return t
    return ""


def last_assistant_text(path, limit=1200):
    try:
        lines = io.open(path, encoding="utf-8", errors="replace").read().splitlines()
    except Exception:
        return ""
    for ln in reversed(lines[-400:]):
        if not ln.strip():
            continue
        try:
            d = json.loads(ln)
        except Exception:
            continue
        if d.get("type") != "assistant":
            continue
        t = _text_of((d.get("message") or {}).get("content"))
        t = (t or "").strip()
        if t:
            return t[:limit]
    return ""


def current_chain(session=""):
    """读本轮链 id。按 session 分文件, 避免并发会话互相覆盖; 无 session 退回共享文件。"""
    for p in _chain_paths(session):
        try:
            v = io.open(p, encoding="utf-8").read().strip()
            if v:
                return v
        except Exception:
            continue
    return ""


def _chain_paths(session):
    paths = []
    if session:
        paths.append(os.path.join(HERE, ".current-chain-" + session))
    paths.append(CHAIN_FILE)
    return paths


def write_current_chain(cid, session=""):
    targets = [os.path.join(HERE, ".current-chain-" + session)] if session else []
    targets.append(CHAIN_FILE)
    for p in targets:
        try:
            with io.open(p, "w", encoding="utf-8") as f:
                f.write(cid or UNFILED)
        except Exception:
            pass
