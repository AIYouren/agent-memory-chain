#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
链启动器 —— 点链卡 = 自动拉起该链的会话(链头文件自动加载 + 延续任务)。

为什么是本地服务: 浏览器不许网页跑本地命令, 所以"点击拉起终端"必须有个本地
进程兜。纯 stdlib(http.server), 零依赖, 只绑 127.0.0.1。

路由:
  GET  /                启动器 UI(链卡, 点即启动)
  GET  /dashboard       完整记忆仪表板(原版 + 链区块 + 按链筛选)
  GET  /api/chains      链数据 JSON
  POST /launch          {"chain": "<id>", "mode": "continue"|"new"} -> 在链目录拉起终端

跑法:
  PYTHONUTF8=1 python _chain_serve.py            # 起服务并打开浏览器
  PYTHONUTF8=1 python _chain_serve.py --port 8791 --no-open
  PYTHONUTF8=1 python _chain_serve.py --dry-run  # /launch 只回命令不真起窗口

桌面入口: `链式记忆库.lnk` -> `_chain_open.cmd`。已在跑(端口被本服务占着)就只开浏览器,
不起第二个; 端口被**别的**程序占着则报错退出(exit 2), 不会把别人的页面弹出来。
⛔ 默认端口从 8788 改 8790: 8787/8788 被模型通道网关占了(8788 上是个 Go 服务,
   访问 /api/chains 回 "404 page not found", 差点被误当成本启动器)。
"""
import argparse
import html
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import _memlog

HERE = Path(__file__).resolve().parent
REG = HERE / "_registry.json"
HOME = Path.home()
WS = HOME / ".deep-memory"
DASH = WS / "memory-dashboard.html"
CLAUDE = "claude"          # 在 PATH 里(npm 全局)
DEFAULT_PROMPT = "继续这条链的任务：先读本目录 CLAUDE.md 的硬约束和下一步，再接着做。"

# 记忆的改/删。⛔ 服务没有账号体系, 写接口靠"启动时生成的一次性 token + 注入页面"挡 CSRF:
# 别的网页打不到这个 token, 所以不能替你删记忆。token 每次重启都换, 不留文件。
TOKEN = secrets.token_hex(12)
TRASH = HERE / "_trash"
JSON_CT = "application/json; charset=utf-8"
# 待定区（临时记忆）：工具在链式记忆库项目里，这里是调用方。
STAGING = HERE / "_staging.py"
MAX_EDIT = 400_000                                  # 单文件上限, 防手滑贴进来一坨
SLUG_RE = re.compile(r"^[A-Za-z0-9_\-.一-鿿]{1,120}$")

DRY = False


# ---------- 数据 ----------

def clean_path(w):
    """work 字段可能带括号备注(如 'E:\\x\\ (v5 名是 ...)'), 取第一个空格/括号前的真路径。"""
    if not w:
        return ""
    for sep in (" (", "（", " ("):
        if sep in w:
            w = w.split(sep)[0]
    return w.strip().rstrip("\\/")   # 去尾斜杠, 免得 "path\" 跟引号打架


def load_chains():
    reg = json.load(io.open(REG, encoding="utf-8"))
    cold = []
    raw = WS / "cold-notes" / "raw.jsonl"
    if raw.exists():
        for line in raw.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line:
                try:
                    cold.append(json.loads(line))
                except ValueError:
                    pass
    out = []
    for a in reg.get("active", []):
        cid = a["id"]
        work = clean_path(a.get("work", ""))
        exists = bool(work) and os.path.isdir(work)
        hdr = os.path.join(work, "CLAUDE.md") if work else ""
        n = sum(1 for e in cold if str(e.get("project", "")) == cid)
        out.append({
            "id": cid,
            "title": a.get("title", cid),
            "status": a.get("status", ""),
            "next": a.get("next", ""),
            "blocker": a.get("blocker", ""),
            "work": work,
            "scripts": a.get("scripts", ""),
            "readme": a.get("readme", ""),
            "deliverable": a.get("deliverable", ""),
            "mem": n,
            "ready": exists,
            "hdr": os.path.exists(hdr) if hdr else False,
        })
    return out


# ---------- 启动 ----------

def launch_spec(chain, mode):
    """新窗口要执行的那一行 + 工作目录 + 窗口标题。

    ⛔ 原实现是 `["cmd","/c","start","chain:<id>","cmd","/k","cd /d ... && claude ..."]`,
    有两个坑(2026-10-16 实测揪出来, 用户看到的就是它)：
      ① `chain:<id>` 本意是**新窗口标题**, 可 subprocess 拼命令行时**只有含空格的参数才加引号**,
         它没空格 -> 没被引住 -> `start` 当它是**要运行的程序** -> 去开 `chain:` 这个本机没注册的
         协议 -> Windows 弹「获取打开此 'chain' 链接的应用 / 浏览 Microsoft Store」。
      ② list2cmdline 拼出的 `\"` 转义 **cmd.exe 不认**(那是 C 运行时的规矩), 里面的
         `cd /d "路径"` 会被切坏。所以这个「启动」按钮**从做出来就没跑通过**。

    改法: 让 cmd 只解析一句不含任何变量的话 ——
      目录 -> Popen 的 `cwd=`（不进命令行，没有路径引号问题）
      新窗口 -> `CREATE_NEW_CONSOLE`（替掉 `start`）
      标题 -> 命令里第一句 `title ...`（`&` 会正确分隔，实测不吞后续命令）
    这么改后命令行里只剩 DEFAULT_PROMPT 这一个常量，registry 里的任何字段都进不来。

    ⛔ 标题别走 STARTUPINFO.lpTitle: cmd.exe 起手就按命令行重设控制台标题, 把它覆盖掉(实测)。
       也**不要**加 STARTF_USESHOWWINDOW —— STARTUPINFO 默认 wShowWindow=0 即 SW_HIDE, 会藏窗口。
    """
    title = re.sub(r"[&|<>^]", "", str(chain.get("title", chain["id"])))[:60]
    flag = "" if mode == "new" else "-c "
    line = 'title 记忆链 · %s & %s %s"%s" & echo. & echo [记忆链] 会话已退出 & pause' % (
        title, CLAUDE, flag, DEFAULT_PROMPT.replace('"', ""))
    return line, clean_path(chain["work"]), title


def do_launch(chain, mode):
    line, work, title = launch_spec(chain, mode)
    if DRY:
        return True, "[dry-run] cwd=%s | %s" % (work, line)
    if not work or not os.path.isdir(work):
        return False, "链目录不存在：%s" % (work or "(空)")
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    try:
        subprocess.Popen(line, shell=True, cwd=work, **kw)
        return True, "已拉起终端：%s（%s）" % (title, work)
    except Exception as e:
        return False, str(e)


# ---------- UI ----------

LAUNCHER_CSS = """
:root{--bg:#0b0d12;--card:#141821;--card2:#1b2029;--fg:#e8ebf0;--mut:#8b93a1;
--line:#262c38;--acc:#7c8cff;--ok:#3ddc97;--warn:#f5a623;--bad:#f0556b;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;}
header{padding:22px 28px 14px;border-bottom:1px solid var(--line);
position:sticky;top:0;background:rgba(11,13,18,.92);backdrop-filter:blur(8px);z-index:9;}
h1{font-size:19px;margin:0;letter-spacing:.3px}
.sub{color:var(--mut);font-size:12.5px;margin-top:5px}
.sub a{color:var(--acc);text-decoration:none}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));
gap:16px;padding:20px 28px 60px;max-width:1600px;margin:0 auto;}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;
padding:16px 18px;cursor:pointer;transition:.15s;position:relative;overflow:hidden;}
.card:hover{border-color:var(--acc);background:var(--card2);transform:translateY(-2px);
box-shadow:0 10px 30px -12px rgba(124,140,255,.45);}
.card.dis{opacity:.45;cursor:not-allowed}
.card.dis:hover{transform:none;border-color:var(--line);box-shadow:none}
.chead{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.chead h2{font-size:15.5px;margin:0}
.cid{font-family:ui-monospace,Consolas,monospace;font-size:11px;color:var(--mut);
background:#0e1117;padding:2px 7px;border-radius:6px;border:1px solid var(--line)}
.pill{font-size:11px;padding:2px 8px;border-radius:999px;border:1px solid var(--line);color:var(--mut)}
.pill.ok{color:var(--ok);border-color:rgba(61,220,151,.4)}
.pill.warn{color:var(--warn);border-color:rgba(245,166,35,.4)}
.status{color:var(--acc);font-size:12px;margin-top:7px}
.blk{color:var(--warn);font-size:12px;margin-top:4px}
.next{margin:10px 0 0;padding:9px 11px;background:#0e1117;border-left:3px solid var(--acc);
border-radius:0 8px 8px 0;font-size:12.5px;line-height:1.6;white-space:pre-wrap;color:#cfd6e2}
.meta{margin-top:10px;font-size:11.5px;color:var(--mut);line-height:1.7}
.meta b{color:var(--fg);font-weight:600}
.meta code{font-family:ui-monospace,Consolas,monospace;color:#9fb0d0;word-break:break-all}
.foot{display:flex;align-items:center;justify-content:space-between;margin-top:13px;
padding-top:11px;border-top:1px solid var(--line)}
.mem{font-size:11.5px;color:var(--mut)}
.go{font-size:12.5px;font-weight:600;color:#0b0d12;background:var(--acc);
padding:6px 14px;border-radius:8px;border:0}
.card:hover .go{background:#93a0ff}
.toast{position:fixed;left:50%;bottom:26px;transform:translateX(-50%) translateY(20px);
background:#1b2029;border:1px solid var(--acc);color:var(--fg);padding:11px 18px;
border-radius:10px;font-size:13px;opacity:0;transition:.25s;pointer-events:none;max-width:80vw}
.toast.on{opacity:1;transform:translateX(-50%) translateY(0)}
"""


def render_launcher(chains):
    ready = sum(1 for c in chains if c["ready"])
    cards = []
    for c in chains:
        dis = "" if c["ready"] else " dis"
        click = "dmLaunch('%s')" % c["id"] if c["ready"] else ""
        meta = []
        if c["work"]:
            meta.append('<div><b>目录</b> <code>%s</code></div>' % html.escape(c["work"]))
        if c["deliverable"]:
            meta.append('<div><b>成品</b> %s</div>' % html.escape(c["deliverable"]))
        hdr = '<span class="pill ok">链头✓</span>' if c["hdr"] else '<span class="pill warn">无链头</span>'
        cards.append("""
<div class="card%s" data-id="%s" onclick="%s">
  <div class="chead"><h2>%s</h2><span class="cid">%s</span>%s</div>
  %s
  %s
  <div class="next">%s</div>
  <div class="meta">%s</div>
  <div class="foot">
    <span class="mem">本链记忆 %d 条</span>
    <button class="go">▶ 启动</button>
  </div>
</div>""" % (
            dis, c["id"], click,
            html.escape(c["title"]), c["id"], hdr,
            '<div class="status">状态：%s</div>' % html.escape(c["status"]) if c["status"] else "",
            '<div class="blk">⛔ %s</div>' % html.escape(c["blocker"]) if c["blocker"] else "",
            html.escape(c["next"] or "（未写下一步）"),
            "".join(meta), c["mem"],
        ))
    body = "\n".join(cards)
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>链启动器 · 记忆链</title><style>%s</style></head><body>
<header>
  <h1>🔗 链启动器</h1>
  <div class="sub">点一条链 → 在该链目录拉起 Claude 会话（链头 CLAUDE.md 自动加载 + 注入本链记忆 + 续上次会话）
  · 就绪 %d/%d 条 · <a href="/dashboard">看记忆仪表板 →</a></div>
</header>
<div class="grid" id="g">%s</div>
<div class="toast" id="t"></div>
<script>
function toast(m,ok){var t=document.getElementById("t");t.textContent=m;
t.style.borderColor=ok?"var(--ok)":"var(--bad)";t.classList.add("on");
clearTimeout(window._tt);window._tt=setTimeout(function(){t.classList.remove("on");},2600);}
function dmLaunch(id){
  var card=document.querySelector('.card[data-id="'+id+'"]');
  toast("正在拉起 "+id+" 的会话…",true);
  fetch("/launch",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({chain:id,mode:"continue"})})
  .then(function(r){return r.json();}).then(function(j){toast(j.msg,j.ok);})
  .catch(function(e){toast("启动失败："+e,false);});
}
</script></body></html>""" % (LAUNCHER_CSS, ready, len(chains), body)


# ---------- 记忆的改/删 ----------

def safe_slug(slug):
    """slug -> 本目录下的 .md 路径; 不合法或不存在返回 None。

    ⛔ 挡目录穿越: 只允许单段名字, 且解析后父目录必须就是记忆目录。
    """
    s = (slug or "").strip()
    if not SLUG_RE.match(s) or s == "MEMORY":
        return None
    p = (HERE / (s + ".md")).resolve()
    if p.parent != HERE.resolve() or not p.is_file():
        return None
    return p


def memory_refs(slug):
    """谁引用了这条记忆 —— 删/改之前必须看的东西。

    两类引用分开报, 因为处理方式不同:
      inbound  = 别的记忆文件里写了 [[slug]]  -> 删了立刻变断链(MEMORY.md §3 查不到这种)
      registry = _registry.json 的 active.file / domains / alias_extras 里挂着它 -> 删了主键漂
    """
    inbound, inreg = [], []
    try:
        import _links
        d = _links.build()
        inbound = sorted({e["source"] for e in d["edges"] if e["target"] == slug})
    except Exception as e:
        inbound = []
        inreg.append("(引用检查失败: %s)" % e)
    try:
        reg = json.load(io.open(REG, encoding="utf-8"))
    except Exception:
        reg = {}
    for a in reg.get("active", []):
        if a.get("file") == slug:
            inreg.append("active[%s].file" % a["id"])
    for dom, lst in (reg.get("domains") or {}).items():
        if slug in (lst or []):
            inreg.append("domains[%s]" % dom)
    for al, tgt in (reg.get("alias_extras") or {}).items():
        if not al.startswith("_") and tgt == slug:
            inreg.append("alias_extras[%s]" % al)
    return {"inbound": inbound, "registry": inreg}


def to_trash(p):
    """备份到 _trash/<时间戳>/ —— ⛔ 删除一律走这里, 不做真删(没有后悔药的东西别做)。"""
    d = TRASH / time.strftime("%Y%m%d-%H%M%S")
    d.mkdir(parents=True, exist_ok=True)
    dst = d / p.name
    i = 1
    while dst.exists():
        dst = d / ("%s.%d%s" % (p.stem, i, p.suffix))
        i += 1
    shutil.copy2(p, dst)
    with io.open(TRASH / "_log.jsonl", "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "file": p.name,
                            "backup": str(dst)}, ensure_ascii=False) + "\n")
    return dst


# ---------- HTTP ----------

class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/":
            self._send(200, render_launcher(load_chains()))
        elif u.path == "/dashboard":
            if DASH.exists():
                # 把写接口要的 token 注入页面。⛔ 只有从这里拿到的页面才有 token,
                # 直接双击打开的 memory-dashboard.html 是只读的(改/删按钮不出现)。
                page = DASH.read_text(encoding="utf-8", errors="replace")
                page = page.replace("</body>",
                                    "<script>window.DM_TOKEN=%s;</script>\n</body>"
                                    % json.dumps(TOKEN), 1)
                self._send(200, page)
            else:
                self._send(404, "仪表板还没生成，先跑 _chain_dash.py")
        elif u.path == "/api/chains":
            self._send(200, json.dumps(load_chains(), ensure_ascii=False), JSON_CT)
        elif u.path == "/api/memory":
            q = urllib.parse.parse_qs(u.query)
            slug = (q.get("slug") or [""])[0]
            p = safe_slug(slug)
            if not p:
                self._send(404, json.dumps({"ok": False, "msg": "没有这条记忆：%s" % slug},
                                           ensure_ascii=False), JSON_CT)
                return
            self._send(200, json.dumps({
                "ok": True, "slug": slug, "path": str(p),
                "bytes": p.stat().st_size,
                "text": p.read_text(encoding="utf-8", errors="replace"),
                "refs": memory_refs(slug),
            }, ensure_ascii=False), JSON_CT)
        elif u.path == "/api/staging":
            self._staging_list(u.query)
            return
        elif u.path == "/api/memlog":
            self._memlog_list(u.query)
            return
        else:
            self._send(404, "not found")

    def _memlog_list(self, query):
        """日志表（A 操作流水 / B 会话流水）。直接读 _memlog.py，别在这儿另解析一份。"""
        q = urllib.parse.parse_qs(query or "")
        kind = (q.get("kind") or [""])[0] or None
        try:
            limit = int((q.get("limit") or ["200"])[0])
        except ValueError:
            limit = 200
        rows = _memlog.read(kind=kind, limit=max(1, min(limit, 1000)))
        self._send(200, json.dumps({"ok": True, "total": len(rows), "items": rows},
                                   ensure_ascii=False), JSON_CT)

    def _staging_list(self, query):
        """待定区条目。走 _staging.py，别在这里重写一份解析——两份必漂。"""
        q = urllib.parse.parse_qs(query or "")
        state = (q.get("state") or ["pending"])[0]
        limit = (q.get("limit") or ["40"])[0]
        cmd = [sys.executable, str(STAGING), "list", "--json", "--state", state, "--limit", str(limit)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            self._send(500, json.dumps({"ok": False, "msg": (r.stderr or r.stdout or "")[-400:]},
                                       ensure_ascii=False), JSON_CT)
            return
        try:
            data = json.loads(r.stdout)
        except ValueError:
            self._send(500, json.dumps({"ok": False, "msg": "staging 输出不是 JSON"},
                                       ensure_ascii=False), JSON_CT)
            return
        self._send(200, json.dumps({"ok": True, **data}, ensure_ascii=False), JSON_CT)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            payload = {}

        if u.path in ("/api/memory/save", "/api/memory/delete"):
            self._memory_write(u.path, payload)
            return
        if u.path == "/api/regen":
            self._regen(payload)
            return
        if u.path in ("/api/staging/keep", "/api/staging/drop"):
            self._staging_act(u.path, payload)
            return
        if u.path != "/launch":
            self._send(404, "not found")
            return
        cid = payload.get("chain", "")
        mode = payload.get("mode", "continue")
        chain = next((c for c in load_chains() if c["id"] == cid), None)
        if not chain:
            self._send(200, json.dumps({"ok": False, "msg": "未知链：%s" % cid}, ensure_ascii=False),
                       JSON_CT)
            return
        if not chain["ready"]:
            self._send(200, json.dumps({"ok": False, "msg": "链目录不存在，先确认 work 路径：%s" % chain["work"]},
                                       ensure_ascii=False), JSON_CT)
            return
        ok, msg = do_launch(chain, mode)
        self._send(200, json.dumps({"ok": ok, "msg": msg}, ensure_ascii=False), JSON_CT)

    def _staging_act(self, path, payload):
        if payload.get("token") != TOKEN and self.headers.get("X-DM-Token") != TOKEN:
            self._send(403, json.dumps({"ok": False, "msg": "token 不对"}, ensure_ascii=False), JSON_CT)
            return
        sid = payload.get("id")
        if not isinstance(sid, int):
            self._send(400, json.dumps({"ok": False, "msg": "缺 id"}, ensure_ascii=False), JSON_CT)
            return
        if path.endswith("/keep"):
            cmd = [sys.executable, str(STAGING), "keep", str(sid)]
            if payload.get("to"):
                cmd += ["--to", str(payload["to"])]
        else:
            cmd = [sys.executable, str(STAGING), "drop", str(sid)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        self._send(200, json.dumps(
            {"ok": r.returncode == 0, "msg": (r.stdout or r.stderr or "").strip()[-400:]},
            ensure_ascii=False), JSON_CT)

    def _regen(self, payload):
        """改完记忆要重跑三脚本(顺序固定) + 刷向量元数据, 否则 registry/MEMORY.md/检索全漂。

        跑之前先落一份 _registry.json 备份 —— 生成器理论上只读它, 但"理论上"不算数。
        """
        if payload.get("token") != TOKEN and self.headers.get("X-DM-Token") != TOKEN:
            self._send(403, json.dumps({"ok": False, "msg": "token 不对"}, ensure_ascii=False), JSON_CT)
            return
        out, failed = [], False
        try:
            shutil.copy2(REG, REG.with_name("_registry.json.bak-regen"))
            for s in ("_chain_header.py", "_chain_dash.py", "_gen_index.py"):
                r = subprocess.run([sys.executable, str(HERE / s)], cwd=str(HERE),
                                   capture_output=True, text=True, timeout=300)
                out.append("%s -> rc=%d" % (s, r.returncode))
                if r.returncode:
                    failed = True
                    out.append((r.stderr or r.stdout or "")[-500:])
                    break
            if not failed:
                venv = HOME / ".deep-memory" / ".venv" / "Scripts" / "python.exe"
                upd = HOME / ".claude" / "skills" / "chroma-hybrid-search" / "scripts" / "update_db.py"
                if venv.exists() and upd.exists():
                    r = subprocess.run([str(venv), str(upd)], capture_output=True, text=True, timeout=900)
                    out.append("update_db.py -> rc=%d" % r.returncode)
                    if r.returncode:
                        failed = True
                        out.append((r.stderr or "")[-400:])
                else:
                    out.append("跳过 update_db.py（没找到 venv 或脚本）")
        except Exception as e:
            failed = True
            out.append("失败: %s" % e)
        _memlog.log("op", "regen_all", "MEMORY.md + 链头 + 仪表板",
                    " / ".join(x.split(" -> ")[0] for x in out if " -> " in x),
                    ok=not failed, src="_chain_serve.py")
        self._send(200, json.dumps({"ok": not failed, "msg": "\n".join(out)}, ensure_ascii=False), JSON_CT)

    def _memory_write(self, path, payload):
        """写记忆。⛔ 三个闸: token / 路径 / 反向引用。"""
        if payload.get("token") != TOKEN and self.headers.get("X-DM-Token") != TOKEN:
            self._send(403, json.dumps(
                {"ok": False, "msg": "token 不对 —— 请从链启动器的 /dashboard 打开本页（直接双击文件是只读的）"},
                ensure_ascii=False), JSON_CT)
            return
        slug = payload.get("slug", "")
        p = safe_slug(slug)
        if not p:
            self._send(404, json.dumps({"ok": False, "msg": "没有这条记忆：%s" % slug},
                                       ensure_ascii=False), JSON_CT)
            return

        if path == "/api/memory/save":
            text = payload.get("text")
            if not isinstance(text, str) or not text.strip():
                self._send(400, json.dumps({"ok": False, "msg": "正文是空的，不写"},
                                           ensure_ascii=False), JSON_CT)
                return
            if len(text.encode("utf-8")) > MAX_EDIT:
                self._send(413, json.dumps({"ok": False, "msg": "太大了（>%d 字节）" % MAX_EDIT},
                                           ensure_ascii=False), JSON_CT)
                return
            bak = to_trash(p)                       # 先留旧版
            p.write_text(text, encoding="utf-8", newline="\n")
            _memlog.log("op", "mem_save", slug,
                        "%d 字节，旧版进 %s" % (len(text.encode("utf-8")), bak.name),
                        src="_chain_serve.py")
            self._send(200, json.dumps({
                "ok": True, "msg": "已存。旧版在 %s —— 记得重跑三脚本 + update_db.py，否则索引漂。" % bak,
                "need_regen": True}, ensure_ascii=False), JSON_CT)
            return

        # delete
        refs = memory_refs(slug)
        if (refs["inbound"] or refs["registry"]) and not payload.get("force"):
            self._send(200, json.dumps({
                "ok": False, "need_force": True, "refs": refs,
                "msg": "还有 %d 处 [[引用]] / %d 处 registry 登记，删了会立刻变死链。要强删再来一次。"
                       % (len(refs["inbound"]), len(refs["registry"]))}, ensure_ascii=False), JSON_CT)
            return
        bak = to_trash(p)
        p.unlink()
        _memlog.log("op", "mem_delete", slug, "备份进 %s" % bak.name, src="_chain_serve.py")
        self._send(200, json.dumps({
            "ok": True, "msg": "已删（备份在 %s，不是真删）。记得重跑三脚本 + update_db.py。" % bak,
            "need_regen": True}, ensure_ascii=False), JSON_CT)


def open_browser(url):
    try:
        subprocess.Popen(["cmd", "/c", "start", "", url], shell=False)
    except Exception:
        pass


def running_here(url):
    """端口上跑的到底是不是本启动器 —— GET /api/chains 能解析成 JSON 才算。

    ⛔ 不能只看"端口被占"就开浏览器: 端口可能被别的程序占着(本机 8787 可能被别的常驻服务占着),
    那样一点桌面快捷方式就会把别人的页面弹出来。
    """
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/chains", timeout=1.5) as r:
            json.loads(r.read() or b"[]")
        return True
    except Exception:
        return False


def main():
    global DRY
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    DRY = args.dry_run
    sys.stdout.reconfigure(encoding="utf-8")

    url = "http://%s:%d/" % (args.host, args.port)
    # ⛔ 先探再绑。不能靠"绑定失败"判"已经在跑": Python 的 HTTPServer 带
    # allow_reuse_address(SO_REUSEADDR), **Windows 上第二次也能绑成功**, 会真起第二个服务
    # (实测: 第二个进程默默 serve_forever 挂住, 双击桌面图标两下就中招)。
    if running_here(url):
        print("链启动器已经在跑, 直接开浏览器: %s" % url)
        if not args.no_open:
            open_browser(url)
        return 0

    try:
        srv = ThreadingHTTPServer((args.host, args.port), H)
    except OSError as e:
        print("端口 %d 被占了(失败码 %s): %s\n换个端口: python _chain_serve.py --port 8791" % (args.port, e.errno, e))
        return 2

    print("链启动器已起: %s   (Ctrl+C 停)" % url)
    if not args.no_open:
        open_browser(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n停了")
    return 0


if __name__ == "__main__":
    # ⛔ 必须 raise SystemExit: 裸 main() 会把返回码吞掉, 退出码永远 0,
    # 桌面 .cmd 里的 `if errorlevel 1 pause` 就白写(踩过)。
    raise SystemExit(main())
