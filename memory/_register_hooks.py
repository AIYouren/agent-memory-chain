# -*- coding: utf-8 -*-
"""把 _recall / _autosave 两条 hook 追加进 ~/.claude/settings.json(幂等)。"""
import io
import json
import os

SETTINGS = os.path.expanduser("~/.claude/settings.json")
MEM = os.path.dirname(os.path.abspath(__file__))


def cmd(script):
    return '"%s"' % os.path.normpath(os.path.join(MEM, script))


def main():
    d = json.load(io.open(SETTINGS, encoding="utf-8"))
    h = d.setdefault("hooks", {})

    recall = {"matcher": "", "hooks": [
        {"type": "command", "command": cmd("_recall-hook.cmd"), "timeout": 10}]}
    autosave = {"matcher": "", "hooks": [
        {"type": "command", "command": cmd("_autosave-hook.cmd"), "timeout": 20}]}
    # ★ 同步到服务器 —— [[feedback-use-the-optimized-route]]「优化必须同步到所有调用点」
    #   每轮 Stop 都推一次,那边才不会落后。hook 内部 start /b 后台跑,不阻塞会话。
    syncsrv = {"matcher": "", "hooks": [
        {"type": "command", "command": cmd("_sync-server-hook.cmd"), "timeout": 10}]}

    def add(ev, entry, marker):
        lst = h.setdefault(ev, [])
        lst[:] = [g for g in lst if marker not in json.dumps(g, ensure_ascii=False)]
        lst.append(entry)

    add("UserPromptSubmit", recall, "_recall-hook.cmd")
    add("Stop", autosave, "_autosave-hook.cmd")
    add("Stop", syncsrv, "_sync-server-hook.cmd")

    json.dump(d, io.open(SETTINGS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for ev in ("UserPromptSubmit", "Stop"):
        print(ev, "->", [g["hooks"][0]["command"] for g in h[ev]])


if __name__ == "__main__":
    main()
