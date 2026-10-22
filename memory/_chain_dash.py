#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""链式记忆仪表板生成器 (2026-10-12)

干什么: 在 deep-memory 原版仪表板(viz.py 产出)的基础上, 注入「🔗 记忆链」区块 ——
        每条链 = 项目 + 脚本/能力 + 记忆条目, 点开就能看到"这链现在什么状态、东西在哪"。
怎么做: 1) 先跑 skill 的 viz.py 刷新原版仪表板(复用它的 UI/CSS/数据管线, 不另起炉灶)
        2) 把链区块注入到网格上方, 写回 memory-dashboard.html
跑法:   PYTHONUTF8=1 python _chain_dash.py
纯标准库 (viz.py 本身也是纯标准库)。
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # auto-memory 目录
REG = HERE / "_registry.json"
HOME = Path.home()
WS = HOME / ".deep-memory"
VIZ = HOME / ".claude/skills/deep-memory/scripts/viz.py"
OUT = WS / "memory-dashboard.html"

ANCHOR_GRID = '<div class="grid" id="dm-grid"></div>'
ANCHOR_BODY = "</body>"
# ⛔ 注入用的锚点不能被模板里的注释/文案抢先命中。生成前把非真实标签处的字面量换掉。



def to_simplified(text):
    """繁体 -> 简体。

    上游 viz.py 的仪表板文案是繁體(記憶儀表板/標籤熱度/無資料…), 本注入区块是简体,
    混排看着糙。这里在读回生成结果后统一转一遍 —— ⛔ 不去改上游 viz.py, 上游保持可升级。
    用 OpenCC(t2s, 词组级, 不是逐字映射, 所以 乾/幹/裡/後 这类不会转错)。
    opencc 不在就原样返回(优雅降级), 并打一行警告 —— 别当成功。
    """
    try:
        from opencc import OpenCC
    except ImportError:
        print("[警告] 没装 opencc, 仪表板文案没转简体(繁体仍会显示)。装了再跑一次: pip install opencc")
        return text
    text = OpenCC("t2s").convert(text)
    # ⛔ t2s 只转**字形**, 台湾用词照旧。这里统一**用词**(跟本记忆库其余部分对齐):
    #    专案->项目, 关键字->关键词, 搜寻->搜索(搜索框 placeholder), 连结->链接(节点 tooltip),
    #    品质->质量(卡片标题)。
    #    刻意不动的: 「资料」—— KB 分类名「课程与学习资料取舍」「学习资料」是正确大陆用词。
    for a, b in (("专案", "项目"), ("关键字", "关键词"), ("搜寻", "搜索"),
                 ("连结", "链接"), ("品质", "质量")):
        text = text.replace(a, b)
    return text

SECTION_TMPL = """
<section id="dm-chains">
<style>
/* ============ A. 视觉基线 —— 抄 shadcn "new-york" + Tailwind zinc 一整套 ============
   本页必须单文件离线, 所以不能引 Tailwind/框架, 只抄它的设计语言:
   zinc 中性色阶 + 单一强调色 + 明确字阶 + 阴影分层 + 圆角三档。 */
:root {
  /* 覆盖 upstream 调色板 -> zinc 中性阶(upstream 原本是 slate 味, 偏灰脏) */
  --bg:#fafafa; --card:#fff; --fg:#09090b; --muted:#71717a; --line:#e4e4e7;
  /* 语义色 + 尺度 */
  --ok:#15803d; --warn:#b45309; --danger:#b91c1c;
  --ok-bg:#f0fdf4; --warn-bg:#fffbeb; --info-bg:#eef2ff; --accent-2:#6366f1;
  --r-sm:6px; --r:10px; --r-lg:14px;
  --sh-1:0 1px 2px rgba(9,9,11,.05); --sh-2:0 4px 14px rgba(9,9,11,.07);
  --fs-xs:11.5px; --fs-sm:12.5px; --fs:13.5px; --fs-lg:16px;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans SC","PingFang SC","Microsoft YaHei UI",sans-serif;
  --mono:ui-monospace,"SFMono-Regular",Consolas,"Cascadia Mono",monospace;
  color-scheme:light dark; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#09090b; --card:#18181b; --fg:#fafafa; --muted:#a1a1aa; --line:#27272a;
    --ok:#4ade80; --warn:#fbbf24; --danger:#f87171;
    --ok-bg:#0c1f14; --warn-bg:#241a06; --info-bg:#1c1b38; --accent-2:#a5b4fc;
    --sh-1:0 1px 2px rgba(0,0,0,.4); --sh-2:0 4px 14px rgba(0,0,0,.5); }
}
:where(button,select,input,a):focus-visible { outline:2px solid var(--accent);
  outline-offset:2px; border-radius:var(--r-sm); }
@media (prefers-reduced-motion: reduce) { * { transition:none !important; animation:none !important; } }

/* ============ B. 全局覆盖 —— 直接改写 upstream viz.py 的观感(同优先级, 后者胜) ============ */
body { font-family:var(--sans); -webkit-font-smoothing:antialiased; }
header { padding:22px 24px 18px; background:var(--card); border-bottom:1px solid var(--line); }
h1 { font-size:21px; letter-spacing:-.02em; }
.sub { font-size:var(--fs-sm); margin-top:6px; line-height:1.65; }
.grid { gap:18px; padding:18px 24px 26px; }
.card { border-radius:var(--r-lg); box-shadow:var(--sh-1); padding:18px; }
.card h2 { font-size:var(--fs); letter-spacing:-.01em; margin-bottom:10px; padding-bottom:9px;
  border-bottom:1px solid var(--line); color:var(--fg); }
/* upstream 的 .bar-row 是 flex + 标签固定宽, 条宽硬封顶 180px → 卡片再宽也填不满。
   改成三列 grid: 标签 / 可伸缩轨道 / 数值, 条宽按百分比撑满。 */
.bar-row { display:grid; grid-template-columns:126px minmax(40px,1fr) 44px;
  align-items:center; gap:9px; margin:5px 0; font-size:var(--fs-xs); }
.bar-row .label { width:auto; font-size:var(--fs-xs); }
.bar-row .bar { height:11px; border-radius:999px;
  background:linear-gradient(90deg,var(--accent),var(--accent-2));
  transition:filter .12s; }
.bar-row:hover .bar { filter:brightness(1.08); }
.bar-row .val { text-align:right; font-variant-numeric:tabular-nums; }
.g-controls input[type=search], .g-controls button { height:30px; border-radius:var(--r-sm);
  font-family:inherit; font-size:var(--fs-xs); padding:0 10px; background:var(--card); }
.g-controls button { cursor:pointer; font-weight:500; }
.g-controls button:hover { background:var(--bg); border-color:var(--accent); }
.legend label { padding:2px 9px 2px 6px; border:1px solid var(--line); border-radius:999px;
  background:var(--card); font-size:var(--fs-xs); }

/* ============ C. 🔗 记忆链区块 ============ */
#dm-chains { padding:22px 24px 0; }
/* 页面总高 8018px, 链区块自己就 5616px —— 没有导航只能一路滚。
   做成通栏吸附条, 左右用负 margin 抵消 #dm-chains 的 24px padding。 */
.dm-nav { position:sticky; top:0; z-index:20; display:flex; align-items:center; gap:4px;
  flex-wrap:wrap; margin:0 -24px 10px; padding:9px 24px;
  background:color-mix(in srgb, var(--bg) 88%, transparent);
  backdrop-filter:blur(8px); border-bottom:1px solid var(--line); }
.dm-nav a { font-size:var(--fs-xs); text-decoration:none; color:var(--muted);
  padding:4px 10px; border-radius:var(--r-sm); border:1px solid transparent; }
.dm-nav a:hover { color:var(--accent); background:var(--card); border-color:var(--line); }
.dm-nav a.is-here { color:var(--accent); background:var(--info-bg); font-weight:500; }
.dm-nav .dm-nav-sp { margin-left:auto; color:var(--muted); font-size:10.5px;
  font-variant-numeric:tabular-nums; }
html { scroll-behavior:smooth; }
#dm-chains, #dm-graph, #dm-cf, #dm-grid { scroll-margin-top:58px; }
@media (prefers-reduced-motion: reduce) { html { scroll-behavior:auto; } }
.dm-sec-head { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.dm-sec-head h2 { font-size:var(--fs-lg); margin:0; letter-spacing:-.015em; }
.dm-badge { font-size:var(--fs-xs); font-variant-numeric:tabular-nums; color:var(--muted);
  background:var(--bg); border:1px solid var(--line); border-radius:999px; padding:1px 9px; }
.dm-cc-sub { color:var(--muted); font-size:var(--fs-xs); margin:6px 0 14px; line-height:1.65; }
.dm-cc-sub b { color:var(--accent); font-weight:500; }
/* 待定区 */
#dm-staging { padding:22px 24px 0; }
.dm-st-row { display:flex; gap:12px; align-items:flex-start; padding:10px 12px; border:1px solid var(--line);
  border-radius:10px; margin-bottom:8px; background:var(--bg); }
.dm-st-main { flex:1; min-width:0; }
.dm-st-topic { font-size:13px; font-weight:500; color:var(--fg); margin:0 0 3px; }
.dm-st-meta { font-size:11px; color:var(--muted); font-family:var(--mono); }
.dm-st-content { font-size:12px; color:var(--muted); margin-top:5px; max-height:66px; overflow:hidden;
  line-height:1.55; }
.dm-st-acts { flex:none; display:flex; gap:6px; }
.dm-st-empty { color:var(--muted); font-size:13px; padding:18px 4px; }

/* 日志表 */
#dm-log { padding:22px 24px 0; }
.dm-lg-row { display:grid; grid-template-columns:96px 22px 92px minmax(0,1.1fr) minmax(0,1.6fr);
  gap:10px; align-items:baseline; padding:7px 12px; border:1px solid var(--line);
  border-radius:8px; margin-bottom:5px; background:var(--bg); font-size:var(--fs-xs); }
.dm-lg-row.is-fail { border-color:var(--warn); background:var(--warn-bg); }
.dm-lg-ts { color:var(--muted); font-family:var(--mono); font-variant-numeric:tabular-nums; }
.dm-lg-kind { text-align:center; font-weight:500; }
.dm-lg-kind.is-op { color:var(--accent); }
.dm-lg-kind.is-session { color:var(--ok); }
.dm-lg-act { color:var(--fg); font-weight:500; }
.dm-lg-obj { color:var(--muted); font-family:var(--mono); overflow:hidden;
  text-overflow:ellipsis; white-space:nowrap; }
.dm-lg-detail { color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
@media (max-width:860px) {
  .dm-lg-row { grid-template-columns:88px 20px 1fr; }
  .dm-lg-obj, .dm-lg-detail { grid-column:1 / -1; white-space:normal; }
}

/* KPI 磁贴行 */
.dm-kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(128px,1fr));
  gap:12px; margin-bottom:18px; }
.dm-kpi { background:var(--card); border:1px solid var(--line); border-radius:var(--r-lg);
  padding:13px 15px; box-shadow:var(--sh-1); }
.dm-kpi b { display:block; font-size:22px; line-height:1.15; letter-spacing:-.02em;
  font-variant-numeric:tabular-nums; }
.dm-kpi span { color:var(--muted); font-size:var(--fs-xs); }
.dm-kpi.is-warn b { color:var(--warn); }
.dm-kpi.is-ok b { color:var(--ok); }
.dm-kpi.is-muted b { color:var(--muted); }
/* 链卡 */
.dm-chain-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(340px,1fr)); gap:14px; }
.dm-chain-card { background:var(--card); border:1px solid var(--line); border-radius:var(--r-lg);
  padding:15px 17px; font-size:var(--fs-sm); line-height:1.6; box-shadow:var(--sh-1);
  cursor:pointer; transition:box-shadow .14s, border-color .14s, transform .14s; }
.dm-chain-card:hover { border-color:var(--accent); box-shadow:var(--sh-2); transform:translateY(-1px); }
.dm-chain-card.dm-on { border-color:var(--accent); box-shadow:0 0 0 1px var(--accent), var(--sh-2); }
.dm-cc-head { display:flex; align-items:center; gap:9px; flex-wrap:wrap; }
.dm-cc-head h3 { font-size:var(--fs); margin:0; letter-spacing:-.01em; }
.dm-cc-id { font-family:var(--mono); font-size:var(--fs-xs); color:var(--muted);
  background:var(--bg); border:1px solid var(--line); border-radius:999px; padding:1px 8px; }
/* ⛔ 状态文案有时是一整句(如「进行中·10-14 改档:主力 GN(2章/天+额外打磨) + RR 两本各 1 章/天」),
   只写 white-space:nowrap 会让 pill 冲出容器 —— 实测溢出 143px、压到时间轴上 133px。
   必须 inline-block + max-width 才吃得住 text-overflow。 */
.dm-pill { margin-left:auto; font-size:var(--fs-xs); font-weight:500; border-radius:999px;
  padding:2px 9px; border:1px solid var(--line); color:var(--muted); background:var(--bg);
  white-space:nowrap; display:inline-block; max-width:100%; overflow:hidden;
  text-overflow:ellipsis; vertical-align:bottom; }
.dm-pill.is-run { color:var(--ok); background:var(--ok-bg); border-color:transparent; }
.dm-pill.is-stop { color:var(--warn); background:var(--warn-bg); border-color:transparent; }
.dm-pill.is-info { color:var(--accent); background:var(--info-bg); border-color:transparent; }
/* ⛔ 某条链的「下一步」可以长到 742px(出海网文那种多段待办), 栅格默认 stretch 会把它
   同一行的另外 3 张卡一起撑到 1154px —— 实测三行 606/1154/629, 共 2417px。
   默认钳 3 行, 要全看再展开。 */
.dm-cc-next { white-space:pre-wrap; margin:11px 0 0; padding:9px 12px; background:var(--bg);
  border:1px solid var(--line); border-left:3px solid var(--accent);
  border-radius:0 var(--r) var(--r) 0; font-size:var(--fs-sm); line-height:1.65;
  display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:3; overflow:hidden; }
.dm-cc-next.is-open { display:block; -webkit-line-clamp:unset; }
.dm-cc-next.is-block { border-left-color:var(--warn); color:var(--warn); }
/* 折叠行: 详情按钮 + 收起时给一眼看得到的摘要 */
.dm-cc-bar { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-top:10px; }
.dm-cc-btn { font:inherit; font-size:var(--fs-xs); height:24px; padding:0 10px; cursor:pointer;
  border:1px solid var(--line); border-radius:var(--r-sm); background:var(--card);
  color:var(--muted); transition:background .12s, border-color .12s, color .12s; }
.dm-cc-btn:hover { background:var(--bg); border-color:var(--accent); color:var(--accent); }
.dm-cc-sum { color:var(--muted); font-size:var(--fs-xs); }
.dm-cc-more[hidden] { display:none; }
.dm-cc-meta { margin-top:11px; border-top:1px solid var(--line); padding-top:10px;
  display:grid; gap:5px; font-size:var(--fs-xs); }
.dm-cc-meta div { display:grid; grid-template-columns:50px 1fr; gap:9px; word-break:break-all; }
.dm-cc-meta b { color:var(--muted); font-weight:500; }
.dm-cc-mem { margin-top:11px; border-top:1px solid var(--line); padding-top:10px;
  color:var(--muted); font-size:var(--fs-xs); }
.dm-cc-mem-chips { display:flex; flex-wrap:wrap; gap:5px; margin-top:7px; }
.dm-cc-mem-chips span { background:var(--bg); border:1px solid var(--line); border-radius:999px;
  padding:2px 9px; color:var(--fg); max-width:100%; overflow:hidden;
  text-overflow:ellipsis; white-space:nowrap; }
/* 记忆关系图 */
#dm-graph { padding:6px 0 0; }
/* 两个视图(轨/网)占同一格, 详情面板永远在右列 —— 不然轨视图里点开的面板是隐藏的 */
.dm-views { display:grid; grid-template-columns:minmax(0,1fr) 252px; gap:14px; align-items:start; }
.dm-views > #dm-rail, .dm-views > #dm-gwrap { grid-column:1; grid-row:1; min-width:0; }
.dm-views > #dm-gpanel { grid-column:2; grid-row:1; }
@media (max-width:1080px) {
  .dm-views { grid-template-columns:minmax(0,1fr); }
  .dm-views > #dm-gpanel { grid-column:1; grid-row:2; }
}
.dm-gbox { background:var(--card); border:1px solid var(--line); border-radius:var(--r-lg);
  padding:12px; box-shadow:var(--sh-1); overflow:hidden; }
.dm-gbox svg { height:520px; }
.dm-gpanel { background:var(--card); border:1px solid var(--line); border-radius:var(--r-lg);
  padding:14px; box-shadow:var(--sh-1); font-size:var(--fs-xs); line-height:1.62; }
.dm-gp-t { font-size:var(--fs-sm); font-weight:600; margin:0 0 2px; word-break:break-all; }
.dm-gp-s { color:var(--muted); margin:0 0 9px; font-size:var(--fs-xs); }
.dm-gp-kv { display:grid; grid-template-columns:44px 1fr; gap:4px 9px; margin:9px 0;
  padding-top:9px; border-top:1px solid var(--line); }
.dm-gp-kv b { color:var(--muted); font-weight:500; }
.dm-gp-lk { margin-top:9px; padding-top:9px; border-top:1px solid var(--line); }
.dm-gp-lk h4 { margin:0 0 5px; font-size:var(--fs-xs); color:var(--muted); font-weight:500; }
.dm-gp-lk a { display:inline-block; margin:0 4px 4px 0; padding:1px 8px; border-radius:999px;
  background:var(--bg); border:1px solid var(--line); color:var(--fg);
  text-decoration:none; cursor:pointer; max-width:100%; overflow:hidden;
  text-overflow:ellipsis; white-space:nowrap; }
.dm-gp-lk a:hover { border-color:var(--accent); color:var(--accent); }
.dm-gp-empty { color:var(--muted); }
.dm-gp-hint { color:var(--muted); }
/* 改 / 删（只有从链启动器的 /dashboard 打开才出现：那时页面被注入 token） */
.dm-gp-act { display:flex; gap:8px; margin-top:11px; padding-top:10px; border-top:1px solid var(--line); }
.dm-btn.is-primary { background:var(--accent); border-color:var(--accent); color:#fff; }
.dm-btn.is-primary:hover { background:var(--accent); color:#fff; filter:brightness(1.08); }
.dm-btn.is-danger:hover { border-color:var(--danger); color:var(--danger); }
@media (prefers-color-scheme: dark) { .dm-btn.is-primary { color:#101014; } }
.dm-gp-edit { width:100%; min-height:280px; margin-top:6px; padding:9px 11px; resize:vertical;
  font:12px/1.55 var(--mono); color:var(--fg); background:var(--bg);
  border:1px solid var(--line); border-radius:var(--r-sm); }
.dm-gp-warn { color:var(--warn); margin:7px 0 0; }
/* 分链轨：每条链一行, 按同一根时间轴铺开 */
.dm-seg { display:inline-flex; border:1px solid var(--line); border-radius:var(--r-sm); overflow:hidden; }
.dm-seg .dm-btn { border:0; border-radius:0; height:28px; }
.dm-seg .dm-btn + .dm-btn { border-left:1px solid var(--line); }
.dm-btn.is-on { background:var(--accent); border-color:var(--accent); color:#fff; }
@media (prefers-color-scheme: dark) { .dm-btn.is-on { color:#101014; } }
.dm-lgdot { display:inline-block; width:9px; height:9px; border-radius:50%; vertical-align:-1px; }
.dm-lgdot-hot { background:#4f46e5; }
.dm-lgdot-cold { background:#7c8ea3; }
.dm-rail { background:var(--card); border:1px solid var(--line); border-radius:var(--r-lg);
  box-shadow:var(--sh-1); padding:14px 16px 16px; overflow:hidden; }
.dm-rail-axis { position:relative; height:16px; margin:0 62px 4px 230px; }
.dm-rail-axis span { position:absolute; transform:translateX(-50%); font-size:10px;
  color:var(--muted); white-space:nowrap; }
.dm-rail-row { display:grid; grid-template-columns:220px minmax(0,1fr) 52px;
  gap:10px; align-items:center; padding:6px 0; border-top:1px solid var(--line); }
.dm-rail-row:first-of-type { border-top:0; }
/* grid 子项默认 min-width:auto, 内容能把 220px 的列撑破(head 实测 363px > 220px)。
   补上 min-width:0 让 pill 的 max-width:100% 真正生效。 */
.dm-rail-head { min-width:0; overflow:hidden; }
.dm-rail-head h3 { margin:0; font-size:var(--fs-sm); font-weight:600; }
.dm-rail-head .dm-pill { margin-left:0; margin-top:3px; }
.dm-rail-head p { margin:3px 0 0; color:var(--muted); font-size:10.5px; line-height:1.45;
  display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
.dm-rail-track { position:relative; height:40px; }
.dm-rail-base { position:absolute; left:0; right:0; top:20px; height:1px; background:var(--line); }
.dm-rail-dot { position:absolute; border-radius:50%;
  transform:translate(-50%,-50%); cursor:pointer; transition:transform .1s; }
/* 热库=里程碑(大、实、带白圈), 冷库=日常活动(小、淡) —— 尺寸差拉开才分得出 */
.dm-rail-dot.is-hot { width:11px; height:11px; background:#4f46e5;
  box-shadow:0 0 0 2px var(--card), 0 0 0 3px rgba(79,70,229,.35); }
.dm-rail-dot.is-cold { width:5px; height:5px; background:#8c9aad; opacity:.75; }
.dm-rail-dot:hover { transform:translate(-50%,-50%) scale(1.7); z-index:3; }
.dm-rail-n { text-align:right; color:var(--muted); font-size:var(--fs-xs);
  font-variant-numeric:tabular-nums; }
.dm-rail-row.is-off .dm-rail-head h3 { color:var(--muted); font-weight:500; }
@media (max-width:900px) { .dm-rail-axis { margin-left:0; } .dm-rail-row { grid-template-columns:1fr; } }
.dm-rail-off { margin-top:8px; padding-top:8px; border-top:1px solid var(--line); }
.dm-rail-off > .dm-btn { font-size:var(--fs-xs); }
.dm-rail-offbody { margin-top:6px; }
/* 筛选区 */
#dm-cf { padding:22px 24px 28px; }
#dm-cf .dm-cf-bar { display:flex; align-items:center; gap:10px; flex-wrap:wrap;
  margin-bottom:14px; background:var(--card); border:1px solid var(--line);
  border-radius:var(--r-lg); padding:12px 15px; box-shadow:var(--sh-1); }
#dm-cf .dm-cf-bar > b { font-size:var(--fs-sm); font-weight:600; }
#dm-cf select { font:inherit; font-size:var(--fs-sm); height:30px; padding:0 8px;
  border:1px solid var(--line); border-radius:var(--r-sm); background:var(--card); color:var(--fg); }
#dm-cf .dm-cf-n { color:var(--muted); font-size:var(--fs-xs); font-variant-numeric:tabular-nums; }
.dm-btn { font:inherit; font-size:var(--fs-xs); height:30px; padding:0 12px; cursor:pointer;
  border:1px solid var(--line); border-radius:var(--r-sm); background:var(--card); color:var(--fg);
  transition:background .12s, border-color .12s, color .12s; }
.dm-btn:hover { background:var(--bg); border-color:var(--accent); color:var(--accent); }
#dm-cf .dm-cf-cols { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr));
  gap:14px; align-items:start; }
#dm-cf .card { padding:15px; }
/* ⛔ 和链卡同一个病: 「标签热度」能到 55+ 行, 栅格 stretch 会把同排另外三张
   (时间趋势 3 行 / 记忆类型 2 行 / 质量 1 行) 一起撑到 1413px。改成卡内滚动。 */
#dm-cf-tags, #dm-cf-time, #dm-cf-mt, #dm-cf-q { max-height:264px; overflow:auto; }
#dm-cf-tags::-webkit-scrollbar, #dm-cf-time::-webkit-scrollbar,
#dm-cf-mt::-webkit-scrollbar, #dm-cf-q::-webkit-scrollbar { width:9px; height:9px; }
#dm-cf-tags::-webkit-scrollbar-thumb, #dm-cf-time::-webkit-scrollbar-thumb,
#dm-cf-mt::-webkit-scrollbar-thumb, #dm-cf-q::-webkit-scrollbar-thumb,
.dm-cf-list::-webkit-scrollbar-thumb { background:var(--line); border-radius:999px; }
#dm-cf-tags::-webkit-scrollbar-thumb:hover, #dm-cf-time::-webkit-scrollbar-thumb:hover,
#dm-cf-mt::-webkit-scrollbar-thumb:hover, #dm-cf-q::-webkit-scrollbar-thumb:hover,
.dm-cf-list::-webkit-scrollbar-thumb:hover { background:var(--muted); }
.dm-cf-list { margin-top:14px; max-height:260px; overflow:auto; background:var(--card);
  border:1px solid var(--line); border-radius:var(--r-lg); padding:4px 15px; box-shadow:var(--sh-1); }
.dm-cf-list div { font-size:var(--fs-xs); color:var(--muted); padding:6px 0;
  border-bottom:1px solid var(--line); display:flex; gap:9px; align-items:baseline; }
.dm-cf-list div:last-child { border-bottom:0; }
.dm-cf-list b { color:var(--fg); font-weight:500; font-family:var(--mono); flex:none; }
.dm-cf-list::-webkit-scrollbar { width:9px; height:9px; }
.dm-cf-list::-webkit-scrollbar-thumb { background:var(--line); border-radius:999px; }
.dm-cf-list::-webkit-scrollbar-thumb:hover { background:var(--muted); }
</style>
<nav class="dm-nav" id="dm-nav">
  <a href="#dm-chains" data-tgt="dm-chains" class="is-here">🔗 记忆链</a>
  <a href="#dm-staging" data-tgt="dm-staging">⏳ 待定区</a>
  <a href="#dm-log" data-tgt="dm-log">📜 日志</a>
  <a href="#dm-graph" data-tgt="dm-graph">📊 分链轨 / 网状</a>
  <a href="#dm-cf" data-tgt="dm-cf">🏷️ 按主题域筛选</a>
  <a href="#dm-grid" data-tgt="dm-grid">📈 原版统计面板</a>
  <span class="dm-nav-sp" id="dm-nav-sp"></span>
</nav>
<div class="dm-sec-head">
  <h2 id="dm-chains-title"></h2>
  <span class="dm-badge" id="dm-chains-badge"></span>
</div>
<div class="dm-cc-sub">每条链的专属规矩在各链目录的 <b>CLAUDE.md</b>（由 _chain_header.py 生成）· <b>点链卡 = 按链筛选下方统计</b><br>
「对话快照」= autosave hook 落的原始对话原文，不算记忆，不进下列任何统计与图表（下游原版面板按冷库全量统计，数字会比这里大）</div>
<div class="dm-kpis" id="dm-kpis"></div>
<div class="dm-chain-grid" id="dm-chain-grid"></div>
<section id="dm-staging">
  <div class="dm-sec-head">
    <h2>⏳ 待定区（临时记忆）</h2>
    <span class="dm-badge" id="dm-staging-badge">…</span>
    <div class="dm-seg">
      <button class="dm-btn is-on" type="button" data-st="pending">待定</button>
      <button class="dm-btn" type="button" data-st="kept">已入正式库</button>
      <button class="dm-btn" type="button" data-st="dropped">判无用</button>
      <button class="dm-btn" type="button" data-st="archived">已归档</button>
    </div>
  </div>
  <div class="dm-cc-sub">跑任务时 autosave 自动落的<b>草稿</b>，不是记忆 · 点「留」进正式库（auto-memory），
    点「弃」只标记不删 · 超过 14 天没处理的自动<b>归档</b>（可捞回，永不删）</div>
  <div id="dm-staging-list"></div>
</section>
<section id="dm-log">
  <div class="dm-sec-head">
    <h2>📜 记忆库日志</h2>
    <span class="dm-badge" id="dm-log-badge">…</span>
    <div class="dm-seg">
      <button class="dm-btn is-on" type="button" data-lg="">全部</button>
      <button class="dm-btn" type="button" data-lg="op">A 操作</button>
      <button class="dm-btn" type="button" data-lg="session">B 会话</button>
    </div>
  </div>
  <div class="dm-cc-sub">记忆库的<b>过程</b>流水 —— 谁、什么时候、动了哪一条、成没成。
    <b>A</b>=操作（keep/弃/归档/捞回/改删记忆/重建索引）· <b>B</b>=一轮会话干了什么（含动过哪些记忆文件）。
    全量在 <b>_memlog.jsonl</b>，追加写不改写；MEMORY.md 末尾那张日志表是它的最近 10 条。</div>
  <div id="dm-log-list"></div>
</section>
<section id="dm-graph">
  <div class="dm-sec-head">
    <h2>🔗 记忆链</h2>
    <span class="dm-badge" id="dm-graph-badge"></span>
    <div class="dm-seg" id="dm-view-seg">
      <button class="dm-btn is-on" type="button" data-view="rail">分链轨</button>
      <button class="dm-btn" type="button" data-view="graph">网状</button>
    </div>
  </div>
  <div class="dm-cc-sub" id="dm-sub-rail">每条链一行，它名下的记忆/冷库条目按<b>同一根时间轴</b>铺开 · <b>点任意点看详情</b> · <span class="dm-lgdot dm-lgdot-hot"></span> 热库记忆 <span class="dm-lgdot dm-lgdot-cold"></span> 冷库条目</div>
  <div class="dm-cc-sub" id="dm-sub-graph" hidden>节点 = 热库记忆 + 冷库条目 + 枢纽 · <b>冷库图层默认在图例里关掉，勾上才显示</b> · 大点 = 链主档 / 枢纽 / 度 ≥ 8</div>
  <div class="dm-views">
    <div class="dm-rail" id="dm-rail"></div>
    <div id="dm-gwrap" hidden><div class="dm-gbox" id="dm-gbox"></div></div>
    <aside class="dm-gpanel" id="dm-gpanel"></aside>
  </div>
</section>
<section id="dm-cf">
  <div class="dm-cf-bar">
    <b>按主题域筛选</b>
    <select id="dm-cf-sel"></select>
    <span class="dm-cf-n" id="dm-cf-n"></span>
    <button class="dm-btn" id="dm-cf-reset" type="button">重置</button>
  </div>
  <div class="dm-cf-cols">
    <div class="card"><h2>🏷️ 标签热度</h2><div id="dm-cf-tags"></div></div>
    <div class="card"><h2>📅 时间趋势</h2><div id="dm-cf-time"></div></div>
    <div class="card"><h2>🧭 记忆类型</h2><div id="dm-cf-mt"></div></div>
    <div class="card"><h2>🔄 质量（raw/reviewed）</h2><div id="dm-cf-q"></div></div>
  </div>
  <div class="dm-cf-list" id="dm-cf-list"></div>
</section>
</section>
<script type="application/json" id="dm-chain-data">__DATA__</script>

<script>
/* 待定区：跑任务落的草稿，留/弃由人定。⛔ 只在 /dashboard 下有 token 时才显示动作按钮——
   直接双击打开的 memory-dashboard.html 是只读的(和改/删记忆同一个约定)。 */
(function () {
  var list = document.getElementById("dm-staging-list");
  if (!list) return;
  var state = "pending";
  // ⛔ 不要在 IIFE 启动时缓存 token：服务端把 DM_TOKEN 注在 body 结束标签前，
  //    比这个脚本晚执行。启动时取到的是空，动作按钮永远退化成提示文案。
  //    ⚠️ 这段注释里**不能出现 body 结束标签的字面量** —— 服务端是按字面字符串
  //    替换第一个匹配点的，写在注释里就会替换到注释中间，把整段 JS 截成语法错误。
  function token() { return window.DM_TOKEN || ""; }

  function btn(label, cls, fn) {
    var b = document.createElement("button");
    b.className = "dm-btn " + cls; b.type = "button"; b.textContent = label;
    b.addEventListener("click", fn); return b;
  }

  function act(path, id, to) {
    fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-DM-Token": token() },
      body: JSON.stringify({ token: token(), id: id, to: to || undefined })
    }).then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) { alert(d.msg || "失败"); return; }
        load();
      })
      .catch(function (e) { alert("请求失败：" + e); });
  }

  function load() {
    list.innerHTML = '<div class="dm-st-empty">加载中…</div>';
    fetch("/api/staging?state=" + encodeURIComponent(state) + "&limit=60")
      .then(function (r) { return r.json(); })
      .then(function (d) {
        list.innerHTML = "";
        var badge = document.getElementById("dm-staging-badge");
        if (badge) badge.textContent = (d.items ? d.items.length : 0) + " / " + (d.total || 0) + " 条";
        if (!d.ok) {
          list.innerHTML = '<div class="dm-st-empty">' + (d.msg || "读不到待定区") +
            "</div>"; return;
        }
        if (!d.items || !d.items.length) {
          list.innerHTML = '<div class="dm-st-empty">（空）</div>'; return;
        }
        d.items.forEach(function (it) {
          var row = document.createElement("div"); row.className = "dm-st-row";
          var main = document.createElement("div"); main.className = "dm-st-main";
          var t = document.createElement("p"); t.className = "dm-st-topic";
          t.textContent = "#" + it.id + "  " + (it.topic || "");
          main.appendChild(t);
          var m = document.createElement("div"); m.className = "dm-st-meta";
          // tags 历史上有字符串/None 两种脏数据，不能直接 .join
          var tg = Array.isArray(it.tags) ? it.tags.join("/") : (it.tags || "");
          m.textContent = [it.date, it.time, it.project, it.skill,
                           tg, it.state].filter(Boolean).join("  ·  ");
          main.appendChild(m);
          if (it.content) {
            var c = document.createElement("div"); c.className = "dm-st-content";
            c.textContent = it.content; main.appendChild(c);
          }
          row.appendChild(main);

          var acts = document.createElement("div"); acts.className = "dm-st-acts";
          if (token() && it.state === "pending") {
            acts.appendChild(btn("留 → 正式库", "is-on", function () {
              var to = prompt("晋升到哪条链的 slug？（留空用条目的 project）", it.project || "");
              if (to === null) return;
              act("/api/staging/keep", it.id, to.trim());
            }));
            acts.appendChild(btn("弃", "", function () {
              if (confirm("标记为无用？（不删除，只是不再出现在待定区）"))
                act("/api/staging/drop", it.id);
            }));
          } else if (!token()) {
            acts.appendChild(btn("从 /dashboard 打开才有动作", "", function () {}));
          }
          row.appendChild(acts);
          list.appendChild(row);
        });
      })
      .catch(function (e) {
        list.innerHTML = '<div class="dm-st-empty">读不到待定区（' + e + "）</div>";
      });
  }

  Array.prototype.forEach.call(
    document.querySelectorAll('#dm-staging [data-st]'),
    function (b) {
      b.addEventListener("click", function () {
        Array.prototype.forEach.call(
          document.querySelectorAll('#dm-staging [data-st]'),
          function (x) { x.classList.remove("is-on"); });
        b.classList.add("is-on");
        state = b.getAttribute("data-st");
        load();
      });
    });

  load();
})();
</script>
<script>
/* 日志表：A=记忆库被改动的流水，B=一轮会话干了什么。只读，没有动作按钮。
   和待定区同一个约定 —— 双击打开的静态页没有本地服务，这里会提示去 /dashboard。 */
(function () {
  var list = document.getElementById("dm-log-list");
  if (!list) return;
  var kind = "";
  var LABEL = {
    keep: "晋升入正式库", drop: "判无用", archive: "归档", restore: "从归档捞回",
    migrate: "补齐字段", regen_index: "重建 MEMORY.md", regen_all: "整库重跑三脚本",
    mem_save: "改记忆文件", mem_delete: "删记忆文件", round: "一轮会话"
  };

  function cell(cls, txt) {
    var d = document.createElement("div");
    d.className = cls; d.textContent = txt || "";
    return d;
  }

  function load() {
    list.innerHTML = '<div class="dm-st-empty">加载中…</div>';
    fetch("/api/memlog?limit=200" + (kind ? "&kind=" + encodeURIComponent(kind) : ""))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        list.innerHTML = "";
        var badge = document.getElementById("dm-log-badge");
        if (badge) badge.textContent = (d.items ? d.items.length : 0) + " 条";
        if (!d.ok) {
          list.innerHTML = '<div class="dm-st-empty">' + (d.msg || "读不到日志") + "</div>";
          return;
        }
        if (!d.items || !d.items.length) {
          list.innerHTML = '<div class="dm-st-empty">（空）</div>';
          return;
        }
        d.items.forEach(function (it) {
          var row = document.createElement("div");
          row.className = "dm-lg-row" + (it.ok === false ? " is-fail" : "");
          row.appendChild(cell("dm-lg-ts", String(it.ts || "").slice(5, 16)));
          row.appendChild(cell("dm-lg-kind " + (it.kind === "op" ? "is-op" : "is-session"),
                               it.kind === "op" ? "A" : "B"));
          row.appendChild(cell("dm-lg-act",
            (it.ok === false ? "✗ " : "") + (LABEL[it.act] || it.act || "")));
          row.appendChild(cell("dm-lg-obj", it.obj));
          row.appendChild(cell("dm-lg-detail", it.detail));
          row.title = [it.ts, it.src, it.session ? "会话 " + it.session : ""]
            .filter(Boolean).join("  ·  ");
          list.appendChild(row);
        });
      })
      .catch(function (e) {
        list.innerHTML = '<div class="dm-st-empty">读不到日志（' + e +
          "）。要动作/要实时看，从 /dashboard 打开。</div>";
      });
  }

  Array.prototype.forEach.call(
    document.querySelectorAll('#dm-log [data-lg]'),
    function (b) {
      b.addEventListener("click", function () {
        Array.prototype.forEach.call(
          document.querySelectorAll('#dm-log [data-lg]'),
          function (x) { x.classList.remove("is-on"); });
        b.classList.add("is-on");
        kind = b.getAttribute("data-lg") || "";
        load();
      });
    });

  load();
})();
</script>
<script>
(function () {
  var el = document.getElementById("dm-chain-data");
  if (!el) return;
  var C = JSON.parse(el.textContent);
  var grid = document.getElementById("dm-chain-grid");
  if (!grid) return;
  document.getElementById("dm-chains-title").textContent = "🔗 记忆链";
  document.getElementById("dm-chains-badge").textContent = C.chains.length + " 条链";
  C.chains.forEach(function (c) {
    var card = document.createElement("div"); card.className = "dm-chain-card"; card.dataset.cid = c.id;
    var head = document.createElement("div"); head.className = "dm-cc-head";
    var t = document.createElement("h3"); t.textContent = c.title; head.appendChild(t);
    var i = document.createElement("span"); i.className = "dm-cc-id"; i.textContent = c.id; head.appendChild(i);
    // 状态做 pill(不再是一行蓝字): 阻塞优先于进行中
    if (c.status) {
      var cls = pillCls(c.status, c.blocker);
      var p = document.createElement("span"); p.className = "dm-pill " + cls;
      p.textContent = c.status; p.title = c.status; head.appendChild(p);
    }
    card.appendChild(head);
    function div(cls, txt) { var d = document.createElement("div"); d.className = cls; d.textContent = txt; return d; }

    // 卡片默认只留「链名 + 状态 + 下一步」，其余收进「详情」——
    // 12 张卡铺开时这是页面最长的一段，展开按钮点一下就在原地看全。
    var bar = document.createElement("div"); bar.className = "dm-cc-bar";
    var more = document.createElement("div"); more.className = "dm-cc-more"; more.hidden = true;
    var sum = ["目录", "脚本", "先读", "成品"].filter(function (k) {
      return { "目录": c.work, "脚本": c.scripts, "先读": c.readme, "成品": c.deliverable }[k];
    });
    if (c.mem_count) sum.push("相关记忆 " + c.mem_count + " 条");

    if (sum.length) {
      var dbtn = document.createElement("button");
      dbtn.type = "button"; dbtn.className = "dm-cc-btn"; dbtn.textContent = "详情 ▾";
      dbtn.addEventListener("click", function (ev) {
        ev.stopPropagation();
        var open = more.hidden; more.hidden = !open;
        dbtn.textContent = "详情 " + (open ? "▴" : "▾");
      });
      bar.appendChild(dbtn);
      var s = document.createElement("span"); s.className = "dm-cc-sum";
      s.textContent = sum.join(" · "); bar.appendChild(s);
    }

    // 钳掉的那几行要能点开, 但**量高度必须等卡片进了 grid** ——
    // detached 元素上 scrollHeight/clientHeight 都是 0, 在循环里量会一律拿到 0,
    // 于是内容被静默截断、按钮一个都不长(实测踩过)。这里只挂节点, 量在循环外做。
    if (c.blocker) card.appendChild(div("dm-cc-next is-block", "⛔ " + c.blocker));
    if (c.next) card.appendChild(div("dm-cc-next", "下一步　" + c.next));
    card.__bar = bar;

    var meta = document.createElement("div"); meta.className = "dm-cc-meta";
    [["目录", c.work], ["脚本", c.scripts], ["先读", c.readme], ["成品", c.deliverable]].forEach(function (kv) {
      if (!kv[1]) return;
      var d = document.createElement("div");
      var b = document.createElement("b"); b.textContent = kv[0]; d.appendChild(b);
      d.appendChild(document.createTextNode(kv[1])); meta.appendChild(d);
    });
    if (meta.children.length) more.appendChild(meta);
    if (c.mem_count) {
      var m = div("dm-cc-mem", "相关记忆 " + c.mem_count + " 条");
      var box = document.createElement("div"); box.className = "dm-cc-mem-chips";
      (c.recent || []).forEach(function (tp) {
        var s = document.createElement("span"); s.textContent = tp; s.title = tp; box.appendChild(s);
      });
      m.appendChild(box); more.appendChild(m);
    }
    card.appendChild(more);
    card.addEventListener("click", function () { dmCfSelect(c.id); });
    grid.appendChild(card);
  });

  // 卡片全部进 DOM 之后才量得准 —— 给被钳住的「下一步 / 阻断」补上展开按钮
  Array.prototype.forEach.call(grid.querySelectorAll(".dm-chain-card"), function (card) {
    var bar = card.__bar;
    if (!bar) return;
    Array.prototype.forEach.call(card.querySelectorAll(".dm-cc-next"), function (node) {
      // 带着 clamp 量不出来, 先放开量到自然高度再收回去
      node.classList.add("is-open");
      var full = node.scrollHeight;
      node.classList.remove("is-open");
      if (full <= node.clientHeight + 4) return;
      var label = node.classList.contains("is-block") ? "展开阻断" : "展开下一步";
      var b = document.createElement("button");
      b.type = "button"; b.className = "dm-cc-btn"; b.textContent = label + " ▾";
      b.addEventListener("click", function (ev) {
        ev.stopPropagation();
        var open = node.classList.toggle("is-open");
        b.textContent = label + (open ? " ▴" : " ▾");
      });
      bar.appendChild(b);
    });
    if (bar.children.length) card.appendChild(bar);
  });

  // ---- 🕸️ 记忆关系图: 复用 viz.py 的 networkGraph(顶层函数) ----
  // ⛔ 时序坑: 本区块被注入在 `<div class="grid">` **之前**, 而上游那段 <script> 在它**之后**
  //    —— 所以解析期这里 typeof networkGraph === "undefined"(实测踩过, 图静默不渲染)。
  //    必须等 load: 那时上游图已建完(图例/节点类名都定了), 再改写 GROUPS 与 groupOf 就只影响我这张。
  // ---- 🔗 记忆链：两个视图共用同一份数据(C.graph)与同一个详情面板 ----
  // 默认是**分链轨**(每条链一行, 按同一根时间轴铺开) —— 链是本库的骨架, 一进来就该看见它。
  // 网状图(复用 viz.py 的 networkGraph)按需构建, 省掉 761 个节点的模拟开销。
  var G = C.graph;
  var panel = document.getElementById("dm-gpanel");
  var byId = {}, out = {}, inn = {};
  if (G) {
    G.nodes.forEach(function (n) { byId[n.id] = n; });
    G.edges.forEach(function (e) {
      (out[e.source] = out[e.source] || []).push(e.target);
      (inn[e.target] = inn[e.target] || []).push(e.source);
    });
  }
  var RAIL_T0 = 0, RAIL_SPAN = 1, graphBuilt = false;

  // 详情面板 + 改/删：分链轨与网状共用, 所以放在 IIFE 顶层
  function chips(title, arr) {
    var wrap = document.createElement("div"); wrap.className = "dm-gp-lk";
    var h = document.createElement("h4"); h.textContent = title; wrap.appendChild(h);
    if (!arr.length) {
      var s = document.createElement("span"); s.className = "dm-gp-empty";
      s.textContent = "（无）"; wrap.appendChild(s); return wrap;
    }
    arr.slice(0, 24).forEach(function (id) {
      var a = document.createElement("a"); a.textContent = id; a.title = id;
      a.addEventListener("click", function () { pick(id); });
      wrap.appendChild(a);
    });
    if (arr.length > 24) {
      var m = document.createElement("span"); m.className = "dm-gp-empty";
      m.textContent = " 等 " + arr.length + " 个"; wrap.appendChild(m);
    }
    return wrap;
  }
  // ---- 改 / 删 / 重新生成: 只有被服务注入 token 的页面才有这些按钮 ----
  // ⛔ 直接双击打开的 memory-dashboard.html 没有 token -> 这排按钮不出现, 也就没有
  //    fetch 打 file:// 的报错。写接口在 _chain_serve.py 里还要再验一次 token。
  function api(path, body) {
    var opt = { method: body ? "POST" : "GET", headers: {} };
    if (body) {
      opt.headers["Content-Type"] = "application/json";
      opt.headers["X-DM-Token"] = window.DM_TOKEN;
      opt.body = JSON.stringify(body);
    }
    return fetch(path, opt).then(function (r) { return r.json(); });
  }
  function regenHint() {
    return "\\n\\n下一步：点右上「重新生成」（三脚本 + 刷向量库），否则索引会漂。";
  }
  function editMem(id) {
    api("/api/memory?slug=" + encodeURIComponent(id)).then(function (d) {
      if (!d.ok) { alert(d.msg); return; }
      panel.innerHTML = "";
      var t = document.createElement("p"); t.className = "dm-gp-t"; t.textContent = "编辑 " + id;
      var meta = document.createElement("p"); meta.className = "dm-gp-s";
      meta.textContent = d.path + "（" + d.bytes + " 字节）";
      var ta = document.createElement("textarea"); ta.className = "dm-gp-edit"; ta.value = d.text;
      var row = document.createElement("div"); row.className = "dm-gp-act";
      var sb = document.createElement("button"); sb.className = "dm-btn is-primary"; sb.textContent = "保存";
      var cb = document.createElement("button"); cb.className = "dm-btn"; cb.textContent = "取消";
      sb.addEventListener("click", function () {
        sb.disabled = true;
        api("/api/memory/save", { slug: id, text: ta.value, token: window.DM_TOKEN }).then(function (r) {
          sb.disabled = false;
          alert(r.msg + (r.ok ? regenHint() : ""));
          if (r.ok) pick(id);
        });
      });
      cb.addEventListener("click", function () { pick(id); });
      row.appendChild(sb); row.appendChild(cb);
      panel.appendChild(t); panel.appendChild(meta); panel.appendChild(ta); panel.appendChild(row);
    });
  }
  function delMem(id) {
    if (!confirm("删除 " + id + " ？\\n\\n不是真删：会备份到 _trash/。")) return;
    function after(r) {
      alert(r.msg + (r.ok ? regenHint() : ""));
      if (r.ok) {
        panel.innerHTML = '<p class="dm-gp-hint">已删除 ' + id +
          '（备份在 _trash/）。点「重新生成」后这张图才会更新。</p>';
      }
    }
    api("/api/memory/delete", { slug: id, token: window.DM_TOKEN }).then(function (r) {
      if (r.ok) { after(r); return; }
      if (!r.need_force) { after(r); return; }
      var refs = r.refs || {};
      var lines = (refs.inbound || []).slice(0, 12).join("\\n  ");
      var reg = (refs.registry || []).slice(0, 12).join("\\n  ");
      if (!confirm("⚠ 还有引用：\\n\\n[[链接]]：" + (refs.inbound || []).length + " 处\\n  " + lines +
                   "\\n\\nregistry：" + (refs.registry || []).length + " 处\\n  " + reg +
                   "\\n\\n删了会立刻变死链。仍然删除？")) return;
      api("/api/memory/delete", { slug: id, token: window.DM_TOKEN, force: true }).then(after);
    });
  }
  function actions(id) {
    var box = document.createElement("div"); box.className = "dm-gp-act";
    var eb = document.createElement("button"); eb.className = "dm-btn"; eb.textContent = "编辑正文";
    eb.addEventListener("click", function () { editMem(id); });
    var db = document.createElement("button"); db.className = "dm-btn is-danger"; db.textContent = "删除";
    db.addEventListener("click", function () { delMem(id); });
    box.appendChild(eb); box.appendChild(db);
    return box;
  }

  function pick(id) {
    var n = byId[id];
    if (!n) return;
    panel.innerHTML = "";
    var t = document.createElement("p"); t.className = "dm-gp-t";
    t.textContent = (n.kind === "cold" ? n.label : id);
    var s = document.createElement("p"); s.className = "dm-gp-s";
    s.textContent = n.desc || "（没写 description）";
    panel.appendChild(t); panel.appendChild(s);
    var kv = document.createElement("div"); kv.className = "dm-gp-kv";
    var rows;
    if (n.kind === "cold") {
      rows = [["日期", (n.date + " " + n.time).trim()], ["冷库", n.project],
              ["类型", n.mtype || "—"], ["质量", n.quality || "—"]];
    } else if (n.kind === "hub") {
      rows = [["枢纽", n.hub], ["热库", n.n_hot + " 条"], ["冷库", n.n_cold + " 条"]];
    } else {
      rows = [["域", n.domain || "—"], ["链", n.chain || "—"],
              ["出/入", (out[id] || []).length + " / " + (inn[id] || []).length]];
    }
    rows.forEach(function (p) {
      var b = document.createElement("b"); b.textContent = p[0];
      var v = document.createElement("span"); v.textContent = p[1];
      kv.appendChild(b); kv.appendChild(v);
    });
    panel.appendChild(kv);
    if (n.kind === "cold") {
      if (n.tags && n.tags.length) panel.appendChild(chips("标签", n.tags));
      panel.appendChild(chips("所属枢纽", inn[id] || []));
      var w = document.createElement("p"); w.className = "dm-gp-hint";
      w.textContent = "冷库是只追加的：这里不提供改/删（要修正就在冷库里追加一条，别改历史）。";
      panel.appendChild(w);
    } else if (n.kind === "hub") {
      panel.appendChild(chips("成员", n.members || []));
    } else {
      panel.appendChild(chips("它引用了", out[id] || []));
      panel.appendChild(chips("谁引用了它", inn[id] || []));
      if (window.DM_TOKEN) panel.appendChild(actions(id));
    }
  }

  function renderMemoryGraph() {
    if (!G || typeof networkGraph !== "function") return;
    var box = document.getElementById("dm-gbox");

    // 深色主题取另一套色(灰/棕/橄榄在深底会糊)
    var DARK = !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
    var gcolor = G.groups.map(function (g) { return DARK ? g.dark : g.light; });
    // ⛔ GROUPS/groupOf 是上游**共用**的全局: networkGraph 只在构造期读它们(实测),
    //    但它的「重置视图」按钮会重读 GROUPS —— 所以我的分组只借这一次, 用完立刻还原,
    //    否则点上游那张图的重置会把它的节点全藏掉(它的 s.grp 在我这 13 个 key 里查不到)。
    var origGroups = GROUPS.slice(), origGroupOf = window.groupOf;
    window.groupOf = function (n) { return "mg" + n.grp; };
    GROUPS.length = 0;
    G.groups.forEach(function (g, i) {
      GROUPS.push({ key: "mg" + i, label: g.name, color: gcolor[i], cls: "mg" + i });
    });
    var gnodes = G.nodes.map(function (n) {
      return { id: n.id, label: n.label, type: n.big ? "project" : "term",
               kind: "mg" + n.grp, weight: Math.min(16, n.deg), grp: n.grp };
    });
    var gpos = {};   // 决定性起点: 按顺序铺一圈, 再由物理模拟收敛
    gnodes.forEach(function (n, i) {
      var a = (i / Math.max(1, gnodes.length)) * Math.PI * 2;
      gpos[n.id] = [400 + Math.cos(a) * 200, 300 + Math.sin(a) * 200];
    });
    networkGraph(box, { nodes: gnodes, edges: G.edges, positions: gpos });
    // 还原上游的全局(见上面时序/共用说明)
    GROUPS.length = 0;
    origGroups.forEach(function (g) { GROUPS.push(g); });
    window.groupOf = origGroupOf;
    // 我这张图的重置按钮换成自己的: 上游那个读 GROUPS, 还原后查不到我的 key 会把节点全藏了。
    // 自己的做法 = 把 13 个图例勾选框重新打勾并派发 change, 借它自己的 refresh 通道。
    var rbtn = box.querySelector(".g-controls button");
    if (rbtn) {
      var nb = rbtn.cloneNode(true);           // clone 不带原监听器
      rbtn.parentNode.replaceChild(nb, rbtn);
      nb.addEventListener("click", function () {
        Array.prototype.forEach.call(
          box.querySelectorAll(".legend input[type=checkbox]"), function (cb) {
            if (!cb.checked) { cb.checked = true; cb.dispatchEvent(new Event("change")); }
          });
      });
    }

    // 冷库 600+ 条默认关掉 —— 一上来全是小点会盖住记忆网络。图例里勾上就显示。
    // 走图例勾选框自己的 change 通道(跟我的重置按钮同一招), 不碰内部状态。
    Array.prototype.forEach.call(box.querySelectorAll(".legend label"), function (lab) {
      if (lab.textContent.indexOf("冷库") < 0) return;
      var cb = lab.querySelector("input");
      if (cb && cb.checked) { cb.checked = false; cb.dispatchEvent(new Event("change")); }
    });

    // 后处理: networkGraph 里 circle 的创建顺序 = nodes 顺序, 借此补正确配色与 tooltip
    var circles = box.querySelectorAll("circle");
    gnodes.forEach(function (n, i) {
      var c = circles[i];
      if (!c) return;
      c.style.fill = gcolor[byId[n.id].grp];
      var tt = c.querySelector("title");
      if (tt) {
        var nd = byId[n.id];
        tt.textContent = nd.kind === "cold"
          ? (nd.label + "（冷库 · " + nd.date + " · " + nd.project + "）")
          : nd.kind === "hub"
            ? (nd.label + "（枢纽 · 热库 " + nd.n_hot + " + 冷库 " + nd.n_cold + "）")
            : (n.id + "（度 " + nd.deg + "，入 " + nd.indeg + "）");
      }
      c.addEventListener("click", function (ev) { ev.stopPropagation(); pick(n.id); });
    });
    panel.innerHTML = '<p class="dm-gp-hint">点任意节点看详情。热库记忆可改可删；冷库条目只读。</p>';
  }

  // ---- 分链轨：每条链一行, 按同一根时间轴铺开 ----
  function pillCls(status, blocker) {
    return (blocker || /受阻|卡住|等他|待拍板/.test(status)) ? "is-stop"
         : /已通|完成|通过|上线|已出|跑通|满额/.test(status) ? "is-run" : "is-info";
  }
  function pad2(n) { return (n < 10 ? "0" : "") + n; }

  function railRow(cid, title, status, nxt, isOff, offKey) {
    var row = document.createElement("div");
    row.className = "dm-rail-row" + (isOff ? " is-off" : "");
    var head = document.createElement("div"); head.className = "dm-rail-head";
    var h = document.createElement("h3"); h.textContent = title; head.appendChild(h);
    if (status) {
      var pl = document.createElement("span"); pl.className = "dm-pill " + pillCls(status, "");
      pl.textContent = status; head.appendChild(pl);
    }
    if (nxt) {
      var q = document.createElement("p"); q.textContent = "下一步　" + nxt; q.title = nxt;
      head.appendChild(q);
    }
    row.appendChild(head);

    // 行归属: 有 rails 的按链; offKey 给了就按 hub 再分桶(未挂链那一堆)
    var members = [];
    G.nodes.forEach(function (n) {
      if (n.kind === "hub") return;
      var on;
      if (offKey) on = !(n.rails && n.rails.length) && (n.hub || "unfiled") === offKey;
      else if (isOff) on = !(n.rails && n.rails.length);
      else on = !!(n.rails && n.rails.indexOf(cid) >= 0);
      if (on) members.push(n);
    });
    members.sort(function (a, b) { return (a.date || "") < (b.date || "") ? -1 : 1; });

    var track = document.createElement("div"); track.className = "dm-rail-track";
    var base = document.createElement("div"); base.className = "dm-rail-base";
    track.appendChild(base);
    members.forEach(function (n, i) {
      var pct = n.date ? (Date.parse(n.date) - RAIL_T0) / RAIL_SPAN * 100 : 50;
      var c = document.createElement("div");
      c.className = "dm-rail-dot " + (n.kind === "hot" ? "is-hot" : "is-cold");
      c.style.left = Math.max(0.4, Math.min(99.6, pct)) + "%";
      c.style.top = (7 + (i % 3) * 12) + "px";     // 三条泳道, 免得同日期的点叠在一起
      c.title = (n.kind === "hot" ? "记忆" : "冷库") + " · " + (n.label || n.id) + "　" + (n.date || "");
      c.addEventListener("click", function (ev) { ev.stopPropagation(); pick(n.id); });
      track.appendChild(c);
    });
    row.appendChild(track);

    var cnt = document.createElement("div"); cnt.className = "dm-rail-n";
    cnt.textContent = members.length + " 条";
    row.appendChild(cnt);
    return row;
  }

  function renderRail() {
    var host = document.getElementById("dm-rail");
    if (!host || !G) return;
    host.innerHTML = "";
    var ds = [];
    G.nodes.forEach(function (n) { if (n.date) ds.push(n.date); });
    ds.sort();
    if (!ds.length) { host.innerHTML = '<p class="dm-gp-hint">没有带日期的节点。</p>'; return; }
    RAIL_T0 = Date.parse(ds[0]);
    RAIL_SPAN = Math.max(1, (Date.parse(ds[ds.length - 1]) || RAIL_T0) - RAIL_T0);

    // 月份刻度(全库共一根轴, 所以能横向比各条链的节奏)
    var axis = document.createElement("div"); axis.className = "dm-rail-axis";
    var m = new Date(RAIL_T0); m.setDate(1); m.setHours(0, 0, 0, 0);
    while (m.getTime() <= RAIL_T0 + RAIL_SPAN) {
      var pct = (m.getTime() - RAIL_T0) / RAIL_SPAN * 100;
      if (pct >= -8 && pct <= 100.5) {   // 左端允许一点点负数, 否则"最早那个月"的刻度会被吃掉
        var sp = document.createElement("span");
        sp.style.left = Math.max(0, Math.min(100, pct)) + "%";
        sp.textContent = m.getMonth() === 0 ? (m.getFullYear() + "-01") : (pad2(m.getMonth() + 1) + "月");
        axis.appendChild(sp);
      }
      m.setMonth(m.getMonth() + 1);
    }
    host.appendChild(axis);

    C.chains.forEach(function (c) {
      host.appendChild(railRow(c.id, c.title, c.status, c.next, false));
    });
    // 未挂链默认收起: 一进来先看见链。展开才按主题域分行。
    // 实测这堆**不是归类错**(topic 命中链别名却归到别处的 = 0 条), 是已完成的主题归档 + 跨链通用知识。
    var offN = 0;
    G.nodes.forEach(function (n) {
      if (n.kind !== "hub" && !(n.rails && n.rails.length)) offN++;
    });
    var det = document.createElement("div"); det.className = "dm-rail-off";
    var btn = document.createElement("button");
    btn.className = "dm-btn"; btn.type = "button";
    var lbl = function (open) {
      return (open ? "▾ " : "▸ ") + "未挂链 " + offN + " 条（不在任何链上）· 按主题域看";
    };
    btn.textContent = lbl(false);
    var body = document.createElement("div"); body.className = "dm-rail-offbody"; body.hidden = true;
    btn.addEventListener("click", function () {
      body.hidden = !body.hidden;
      btn.textContent = lbl(!body.hidden);
    });
    det.appendChild(btn); det.appendChild(body);
    (G.offgroups || []).forEach(function (g) {
      body.appendChild(railRow("", g.label + "（热 " + g.hot + " + 冷 " + g.cold + "）", "", "", true, g.key));
    });
    host.appendChild(det);
  }

  // ---- 视图切换 + 只出现一次的东西(徽章/断链警告/重新生成) ----
  function setView(v) {
    var isRail = v !== "graph";
    document.getElementById("dm-rail").hidden = !isRail;
    document.getElementById("dm-gwrap").hidden = isRail;
    document.getElementById("dm-sub-rail").hidden = !isRail;
    document.getElementById("dm-sub-graph").hidden = isRail;
    Array.prototype.forEach.call(document.querySelectorAll("#dm-view-seg .dm-btn"), function (b) {
      b.classList.toggle("is-on", b.getAttribute("data-view") === (isRail ? "rail" : "graph"));
    });
    // 网状按需构建: 761 个节点的力导向模拟不该在你只想看轨的时候白跑
    if (!isRail && !graphBuilt) { graphBuilt = true; renderMemoryGraph(); }
  }

  function bootExtras() {
    if (G) {
      var nHot = 0, nCold = 0, nHub = 0;
      G.nodes.forEach(function (n) {
        if (n.kind === "cold") nCold++; else if (n.kind === "hub") nHub++; else nHot++;
      });
      document.getElementById("dm-graph-badge").textContent =
        "热库 " + nHot + " · 冷库 " + nCold + " · 枢纽 " + nHub;
      if (G.broken && G.broken.length) {
        var bw = document.createElement("p"); bw.className = "dm-gp-warn";
        bw.textContent = "⚠ 另有 " + G.broken.length + " 个链接目标指向不存在的文件（断链，不在这张图里）";
        var sec = document.getElementById("dm-graph"), rail = document.getElementById("dm-rail");
        if (sec && rail) sec.insertBefore(bw, rail.parentNode);
      }
    }
    if (window.DM_TOKEN) {   // 只有被服务注入 token 的页面才有"重新生成"（要跑子进程）
      var rb = document.createElement("button");
      rb.className = "dm-btn"; rb.textContent = "重新生成";
      rb.style.marginLeft = "auto";
      rb.addEventListener("click", function () {
        rb.disabled = true; rb.textContent = "重生成中…";
        api("/api/regen", { token: window.DM_TOKEN }).then(function (r) {
          rb.disabled = false; rb.textContent = "重新生成";
          alert((r.ok ? "好了\\n\\n" : "有一步失败\\n\\n") + r.msg);
          if (r.ok) location.reload();
        });
      });
      var head = document.querySelector("#dm-graph .dm-sec-head");
      if (head) head.appendChild(rb);
    }
  }

  function bootMemoryViews() {
    bootExtras();
    if (G) renderRail();
    Array.prototype.forEach.call(document.querySelectorAll("#dm-view-seg .dm-btn"), function (b) {
      b.addEventListener("click", function () { setView(b.getAttribute("data-view")); });
    });
    setView("rail");
    if (!G) document.getElementById("dm-rail").innerHTML =
      '<p class="dm-gp-hint">拿不到记忆链接数据（_links.py 没跑通？）。</p>';
  }

  if (document.readyState === "complete") bootMemoryViews();
  else window.addEventListener("load", bootMemoryViews);

  // ---- 吸顶导航: 高亮当前区块 + 右侧报进度(这页能长到 8000px, 没进度感就只能瞎滚) ----
  (function () {
    var nav = document.getElementById("dm-nav");
    if (!nav) return;
    var links = Array.prototype.slice.call(nav.querySelectorAll("a[data-tgt]"));
    var sp = document.getElementById("dm-nav-sp");
    function sync() {
      var mid = window.scrollY + 120, here = links[0];
      links.forEach(function (a) {
        var t = document.getElementById(a.dataset.tgt);
        if (t && t.getBoundingClientRect().top + window.scrollY <= mid) here = a;
      });
      links.forEach(function (a) { a.classList.toggle("is-here", a === here); });
      if (!sp) return;
      var h = document.documentElement.scrollHeight, vh = window.innerHeight;
      var pct = h > vh ? Math.round(window.scrollY / (h - vh) * 100) : 100;
      sp.textContent = "已滚 " + Math.min(100, Math.max(0, pct)) + "% · 页高 " + h + "px";
    }
    window.addEventListener("scroll", sync, { passive: true });
    window.addEventListener("resize", sync);
    sync();
  })();

  // ---- 按链筛选 ----
  var COLD = C.cold || [];
  var sel = document.getElementById("dm-cf-sel");
  var ALL = "__ALL__";
  function opt(v, label) { var o = document.createElement("option"); o.value = v; o.textContent = label; return o; }
  sel.appendChild(opt(ALL, "全部链（" + COLD.length + "）"));
  // 只有确有归属的链 id 才列出(加 unfiled)
  var projects = {};
  COLD.forEach(function (e) { projects[e.p] = (projects[e.p] || 0) + 1; });
  var ids = C.chains.map(function (c) { return c.id; });

  // ---- KPI 磁贴: 冷库去向一眼看清(已归链 / 主题域 / unfiled) ----
  var nOwned = 0, nArea = 0, nUnfiled = 0;
  COLD.forEach(function (e) {
    if (e.p === "unfiled") nUnfiled++;
    else if (ids.indexOf(e.p) >= 0) nOwned++;
    else nArea++;
  });
  var kbox = document.getElementById("dm-kpis");
  // ⛔ COLD 里已经没有 autosave 快照了(split_chatlog 在 Python 侧切掉),
  //    但得把它单独摆出来 —— 藏起来会让人以为冷库就这么多。
  [["冷库记忆", COLD.length, ""], ["在跑的链", C.chains.length, "is-ok"],
   ["已归链", nOwned, "is-ok"], ["主题域", nArea, ""],
   ["未归档", nUnfiled, nUnfiled > 80 ? "is-warn" : ""],
   ["对话快照", C.chatlog || 0, "is-muted"]].forEach(function (k) {
    var d = document.createElement("div"); d.className = "dm-kpi " + k[2];
    var b = document.createElement("b"); b.textContent = k[1];
    var s = document.createElement("span"); s.textContent = k[0];
    d.appendChild(b); d.appendChild(s); kbox.appendChild(d);
  });
  ids.forEach(function (id) { if (projects[id]) sel.appendChild(opt(id, id + "（" + projects[id] + "）")); });
  if (projects["unfiled"]) sel.appendChild(opt("unfiled", "unfiled · 跨链通用（" + projects["unfiled"] + "）"));
  // 其余零散 project 值(未迁移的 cwd 名)
  Object.keys(projects).sort().forEach(function (p) {
    if (p === "unfiled" || ids.indexOf(p) >= 0) return;
    sel.appendChild(opt(p, p + "（" + projects[p] + "）"));
  });

  function tally(rows, key) {
    var m = {};
    rows.forEach(function (e) {
      var v = key(e);
      (Array.isArray(v) ? v : [v]).forEach(function (x) {
        x = x || "(未标)"; m[x] = (m[x] || 0) + 1;
      });
    });
    return Object.keys(m).map(function (k) { return [k, m[k]]; })
      .sort(function (a, b) { return b[1] - a[1]; });
  }
  function top(rows, n) { return rows.slice(0, n); }

  function render(cid) {
    var rows = COLD.filter(function (e) { return cid === ALL || e.p === cid; });
    document.getElementById("dm-cf-n").textContent =
      (cid === ALL ? "全部" : cid) + " · " + rows.length + " 条";
    ["dm-cf-tags", "dm-cf-time", "dm-cf-mt", "dm-cf-q"].forEach(function (id) {
      document.getElementById(id).innerHTML = "";
    });
    // 自绘条形图: 不借 viz.py 的 barChart(它把条宽硬封顶 180px)
    function bc(c, rows) {
      c.innerHTML = "";
      if (!rows.length) { var e = document.createElement("div"); e.className = "empty";
        e.textContent = "无数据"; c.appendChild(e); return; }
      var max = Math.max.apply(null, [1].concat(rows.map(function (r) { return r[1]; })));
      rows.forEach(function (r) {
        var row = document.createElement("div"); row.className = "bar-row";
        var l = document.createElement("div"); l.className = "label"; l.textContent = r[0]; l.title = r[0];
        var b = document.createElement("div"); b.className = "bar";
        b.style.width = Math.max(1.5, (r[1] / max) * 100) + "%";
        var v = document.createElement("div"); v.className = "val"; v.textContent = r[1];
        row.appendChild(l); row.appendChild(b); row.appendChild(v); c.appendChild(row);
      });
    }
    bc(document.getElementById("dm-cf-tags"), top(tally(rows, function (e) { return e.t; }), 20));
    bc(document.getElementById("dm-cf-time"), tally(rows, function (e) { return e.d; })
      .sort(function (a, b) { return a[0] < b[0] ? -1 : 1; }));
    bc(document.getElementById("dm-cf-mt"), tally(rows, function (e) { return e.m; }));
    bc(document.getElementById("dm-cf-q"), tally(rows, function (e) { return e.q; }));
    // 明细
    var list = document.getElementById("dm-cf-list");
    list.innerHTML = "";
    rows.slice(-60).reverse().forEach(function (e) {
      var d = document.createElement("div");
      var b = document.createElement("b"); b.textContent = e.p; d.appendChild(b);
      d.appendChild(document.createTextNode("  " + e.d + "  " + (e.t || []).join("/")));
      list.appendChild(d);
    });
  }

  window.dmCfSelect = function (cid) {
    sel.value = cid;
    Array.prototype.forEach.call(grid.querySelectorAll(".dm-chain-card"), function (c) {
      c.classList.toggle("dm-on", c.dataset.cid === cid);
    });
    render(cid);
  };
  sel.addEventListener("change", function () { window.dmCfSelect(sel.value); });
  document.getElementById("dm-cf-reset").addEventListener("click", function () { window.dmCfSelect(ALL); });
  render(ALL);

  // viz.py 在解析期就把 6 张图表画完了(早于本脚本), 改不动它的函数, 只能事后按 .val 重算宽度,
  // 让条宽按百分比撑满卡片(它原本硬封顶 180px)。
  function fluidizeBars() {
    var boxes = [];
    Array.prototype.forEach.call(document.querySelectorAll(".bar-row"), function (row) {
      if (boxes.indexOf(row.parentNode) < 0) boxes.push(row.parentNode);
    });
    boxes.forEach(function (box) {
      var items = [];
      Array.prototype.forEach.call(box.querySelectorAll(".bar-row"), function (r) {
        var b = r.querySelector(".bar"), v = r.querySelector(".val");
        var n = v ? parseFloat(v.textContent) : NaN;
        if (b && !isNaN(n)) items.push([b, n]);
      });
      if (!items.length) return;
      var max = Math.max.apply(null, [1].concat(items.map(function (t) { return t[1]; })));
      items.forEach(function (t) {
        t[0].style.width = Math.max(1.5, (t[1] / max) * 100) + "%";
      });
    });
  }
  fluidizeBars();

  window.addEventListener("load", function () {
    fluidizeBars();
    var sum = document.getElementById("dm-summary");
    if (sum) sum.textContent += " · 链 " + C.chains.length;
  });
})();
</script>
"""


def load_cold():
    """读冷库条目; 坏行跳过。"""
    p = WS / "cold-notes" / "raw.jsonl"
    out = []
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def split_chatlog(cold):
    """把 autosave hook 落的**原始对话快照**从「记忆」里切出去。

    ⛔ 根因: autosave 被要求纯 stdlib、零 token, 所以它没法抽要点, 只能把本轮原文
       落脚 —— topic 实测是「先存着明天弄」「不能加名单？」这种, 不是记忆。
       量出来它是**整库第一大标签**(55 条), 还把 105 条 unfiled 里的 42 条顶着。
    处理: 数据保留(可逆), 只是不进任何视图/统计 —— **卡口只在这一个地方**,
       别在下游 load_cold/build_graph/KPI 各写各的过滤(会漂)。
    """
    keep, log = [], []
    for e in cold:
        (log if "autosave" in (e.get("tags") or []) else keep).append(e)
    return keep, log


def chain_recent(cold, chain):
    """一条链命中的冷条目。

    10-13 起 project 字段已迁移成链 id, 所以先按 `project == 链id` 精确归属
    (这是准的); 老条目/未迁移的再退回别名关键字匹配。
    """
    cid = chain["id"]
    keys = [cid] + chain.get("aliases", [])
    hits = []
    for e in cold:
        if str(e.get("project", "")) == cid:
            hits.append(str(e.get("topic", ""))[:70])
            continue
        text = " ".join(str(e.get(k, "")) for k in ("topic", "tags", "skill", "project"))
        if any(k in text for k in keys):
            hits.append(str(e.get("topic", ""))[:70])
    return len(hits), hits[-6:][::-1]


# 记忆关系图的分组(归并后的域) + 配色。
# 配色抄现成的分类色板(Tableau10 打底 + 3 个同族补色), 不自己编 —— 分类色要的是"互相可分",
# 不是好看。⛔ 灰/棕/橄榄这三个偏浊, 深色主题下会糊, 所以 light/dark 给两套值。
MG_COLORS = [
    ("#4f46e5", "#818cf8"),   # 链主档  (跟仪表板强调色一致)
    ("#4c78a8", "#7fb3e0"),   # 方法纪律
    ("#f58518", "#ffa94d"),   # 模型通道
    ("#e45756", "#ff7b7a"),   # PPT课件
    ("#72b7b2", "#8ed3ce"),   # 桌面自动化
    ("#54a24b", "#7dc973"),   # 剪辑成片
    ("#eeca3b", "#f7dd6b"),   # 出海接单
    ("#b279a2", "#d99ec9"),   # 示例域
    ("#ff9da6", "#ffbbc2"),   # 暂存待办
    ("#9d755d", "#c79e83"),   # 写作
    ("#bab0ac", "#d8cfcb"),   # 系统磁盘
    ("#5fa8d3", "#8ccbf0"),   # 网安
    ("#8f9779", "#b0b894"),   # 其他
    ("#27272a", "#e4e4e7"),   # 枢纽 (近黑/近白: 大点+常驻标签, 当"结构"看而不是一个类别)
    ("#7c8ea3", "#93a7bd"),   # 冷库 (冷灰蓝: 600+ 个小点用单一色, 不然一团花)
]
MG_MIN_DOM = 5      # 文件数 >= 这个数的域才单列一色, 否则并进「其他」
MG_HUB_DEG = 8      # 度 >= 这个数就当枢纽, 放大并常驻标签

# 热库的「域」和冷库的「project」是**两套词汇**(域「网安」 vs project「security-lab」)。
# 这张手工映射把两套并到同一批枢纽上 —— 不桥的话两层永远连不起来, 图就是两个孤岛。
AREA_BRIDGE = {
    "网安": "security-lab", "PPT课件": "ai-ppt-studio", "录音语音": "transcribe-product",
    "模型通道": "model-channels", "桌面自动化": "gui-automation", "剪辑成片": "video-ffmpeg",
    "写作": "novel-pipeline", "系统磁盘": "system-maintenance",
    "出海接单": "account-and-payment", "方法纪律": "tool-selection",
    "GitHub月榜": "github-digest", "暂存待办": "backlog",
}
MG_HUB_MIN = 4      # 枢纽的成员数(热+冷)不到这个数就并进「其他」


def build_graph(cold):
    """记忆之间的网: 节点 = 热库记忆文件 + 冷库条目 + 枢纽, 边 = 双方括号链接 + 归属。

    复用 viz.py 的 networkGraph 渲染, 平移/缩放/拖拽/搜索/图例白拿。
    三层:
      hot   热库记忆(125)   边 = 文件里写的双方括号链接; 按域着色
      cold  冷库条目(600+)  挂到它的 project 枢纽上; 单一色(默认在图例里关掉)
      hub   枢纽            链 id 与主题域**并成一批**, 热库冷库都往它上面挂
    _links 模块不在就返回 None(仪表板照常出, 只是没这张图)。
    """
    try:
        import _links
    except Exception:
        return None
    try:
        d = _links.build()
    except Exception:
        return None
    reg = d["reg"]
    active_ids = {a["id"] for a in reg.get("active", [])}
    titles = {a["id"]: a.get("title", a["id"]) for a in reg.get("active", [])}
    chain_of = {(a.get("file") or a["id"]): a["id"] for a in reg.get("active", [])}
    own = d["own"]

    # ---- 1) 热库节点的域分组(给颜色) ----
    cnt = {}
    for s in d["slugset"]:
        o = own.get(s, "unfiled")
        if o not in active_ids:
            cnt[o] = cnt.get(o, 0) + 1
    doms = [k for k, v in sorted(cnt.items(), key=lambda x: (-x[1], x[0])) if v >= MG_MIN_DOM]
    names = ["链主档"] + doms + ["其他", "枢纽", "冷库"]
    gid = {g: i for i, g in enumerate(names)}
    G_HUB, G_COLD = gid["枢纽"], gid["冷库"]

    # ---- 2) 枢纽 key: 热库归一 ----
    def hub_of_hot(slug, dom):
        if slug in chain_of:
            return chain_of[slug]
        return AREA_BRIDGE.get(dom, dom or "unfiled")

    # 分链轨的行归属: 一个记忆可以**同时**上多条链 —— 链主档直接引用它的就算这条链的(1 跳),
    # 所以 ~50 个记忆会出现在轨上(不是只有 12 个链主档)。冷库按 project 归。
    order_idx = {a["id"]: i for i, a in enumerate(reg.get("active", []))}
    link_src = {}
    for e in d["edges"]:
        link_src.setdefault(e["target"], set()).add(e["source"])

    def rails_of_hot(slug):
        rs = set()
        if slug in chain_of:
            rs.add(chain_of[slug])
        for src in link_src.get(slug, ()):
            if src in chain_of:
                rs.add(chain_of[src])
        return sorted(rs, key=lambda c: order_idx.get(c, 99))

    nodes, hub_members = [], {}
    for n in d["nodes"]:
        s = n["id"]
        o = own.get(s, "unfiled")
        dom = "" if o in active_ids else o
        g = "链主档" if s in chain_of else (o if o in gid else "其他")
        hk = hub_of_hot(s, dom)
        hub_members.setdefault(hk, {"hot": [], "cold": []})["hot"].append(s)
        nodes.append({
            "id": s, "label": s, "desc": (n.get("desc") or "")[:140], "kind": "hot",
            "deg": n["deg"], "indeg": n["in"], "grp": gid[g],
            "date": n.get("mtime", ""),
            "chain": chain_of.get(s, ""), "domain": dom, "hub": hk,
            "rails": rails_of_hot(s),
            "big": (s in chain_of) or n["deg"] >= MG_HUB_DEG,
        })
    by_id = {n["id"]: n for n in nodes}

    # ---- 3) 冷库节点: 挂到它的 project 枢纽 ----
    edges = list(d["edges"])
    for i, e in enumerate(cold):
        cid = "cold:%d" % i
        proj = str(e.get("project") or "").strip() or "unfiled"
        if proj == "unfiled":
            proj = AREA_BRIDGE.get("", "unfiled")
        topic = str(e.get("topic") or "(无标题)")
        hub_members.setdefault(proj, {"hot": [], "cold": []})["cold"].append(cid)
        nodes.append({
            "id": cid, "label": topic[:44], "kind": "cold", "grp": G_COLD,
            "desc": str(e.get("content") or "")[:200],
            "date": str(e.get("date") or ""), "time": str(e.get("time") or ""),
            "project": proj, "mtype": str(e.get("memory_type") or ""),
            "quality": str(e.get("quality") or ""), "skill": str(e.get("skill") or ""),
            "tags": [str(t) for t in (e.get("tags") or [])][:12],
            "deg": 1, "indeg": 0, "hub": proj,
            "rails": sorted({proj} & active_ids, key=lambda c: order_idx.get(c, 99)),
            "big": False,
        })

    # ---- 4) 枢纽节点: 成员不够多的并进「其他」 ----
    merged = {}
    for k, m in hub_members.items():
        n_all = len(m["hot"]) + len(m["cold"])
        k2 = k if n_all >= MG_HUB_MIN else "其他"
        tgt = merged.setdefault(k2, {"hot": [], "cold": []})
        tgt["hot"] += m["hot"]
        tgt["cold"] += m["cold"]
    hub_meta = []
    for k, m in sorted(merged.items(), key=lambda x: -(len(x[1]["hot"]) + len(x[1]["cold"]))):
        n_all = len(m["hot"]) + len(m["cold"])
        if n_all < MG_HUB_MIN:
            continue
        hid = "hub:" + k
        nodes.append({
            "id": hid, "label": (titles.get(k) or k)[:22], "kind": "hub", "grp": G_HUB,
            "hub": k, "deg": n_all, "indeg": 0, "big": True,
            "n_hot": len(m["hot"]), "n_cold": len(m["cold"]),
            "members": (m["hot"] + m["cold"])[:40],
            "desc": "枢纽：热库 %d 条 + 冷库 %d 条" % (len(m["hot"]), len(m["cold"])),
        })
        for s in m["hot"] + m["cold"]:
            edges.append({"source": hid, "target": s})

    # ---- 5) 未挂链的那一堆按域/项目分桶 ----
    # 实测未挂链 = 热库 83 + 冷库 444; 它们**不是归类错**(查过: topic 命中链别名却被归到别处的 = 0 条),
    # 就是已完成的主题归档 + 跨链通用知识。挤成一条灰带看不出是什么, 所以拆开给轨视图用。
    off = {}
    for n in nodes:
        if n.get("kind") == "hub" or (n.get("rails") or []):
            continue
        k = n.get("hub") or "unfiled"
        b = off.setdefault(k, {"hot": 0, "cold": 0})
        b["cold" if n.get("kind") == "cold" else "hot"] += 1
    rev = {}                                  # 反向: 冷库 project -> 热库域名(显示成 "ai-ppt-studio（PPT课件）")
    for dom, area in AREA_BRIDGE.items():
        rev.setdefault(area, dom)
    offgroups, rest_h, rest_c = [], 0, 0
    for k, b in sorted(off.items(), key=lambda x: -(x[1]["hot"] + x[1]["cold"])):
        tot = b["hot"] + b["cold"]
        if tot < MG_HUB_MIN:
            rest_h += b["hot"]
            rest_c += b["cold"]
            continue
        offgroups.append({"key": k, "label": k + ("（%s）" % rev[k] if k in rev else ""),
                          "hot": b["hot"], "cold": b["cold"], "n": tot})
    if rest_h + rest_c:
        offgroups.append({"key": "其他", "label": "其他零散", "hot": rest_h, "cold": rest_c,
                          "n": rest_h + rest_c})

    return {
        "groups": [{"name": nm, "light": MG_COLORS[i][0], "dark": MG_COLORS[i][1]}
                   for i, nm in enumerate(names)],
        "nodes": nodes,
        "edges": edges,
        "broken": sorted({b["target"] for b in d["broken"]}),
        "n_cold": len(cold),
        "offgroups": offgroups,
    }


def build_payload(reg, cold):
    chains = []
    for a in reg["active"]:
        n, recent = chain_recent(cold, a)
        chains.append({
            "id": a["id"],
            "title": a.get("title", a["id"]),
            "status": a.get("status", ""),
            "next": a.get("next", ""),
            "blocker": a.get("blocker", ""),
            "work": a.get("work", ""),
            "scripts": a.get("scripts", ""),
            "readme": a.get("readme", ""),
            "deliverable": a.get("deliverable", ""),
            "mem_count": n,
            "recent": recent,
        })
    # 原始冷条目(压缩字段) 给前端「按链筛选」用
    raw = []
    for e in cold:
        raw.append({
            "d": str(e.get("date", ""))[:10],
            "p": str(e.get("project", "")) or "(未标)",
            "t": [str(x) for x in (e.get("tags") or [])],
            "m": str(e.get("memory_type", "")) or "(未标)",
            "q": str(e.get("quality", "")) or "(未标)",
        })
    return {"chains": chains, "cold": raw, "graph": build_graph(cold)}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    # 1) 刷新原版仪表板 (纯标准库脚本, 用当前 python 即可)
    r = subprocess.run([sys.executable, str(VIZ), "--workspace", str(WS), "--output", str(OUT)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("viz.py 失败:\n" + (r.stderr or "")[-2000:])
        return 1
    html = to_simplified(OUT.read_text(encoding="utf-8"))

    # 2) 注入链区块
    reg = json.loads(REG.read_text(encoding="utf-8"))
    cold, chatlog = split_chatlog(load_cold())
    payload = build_payload(reg, cold)
    payload["chatlog"] = len(chatlog)
    data_json = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026")
    section = SECTION_TMPL.replace("__DATA__", data_json)

    if ANCHOR_GRID not in html or ANCHOR_BODY not in html:
        print("找不到注入锚点, 仪表板结构可能变了")
        return 1
    html = html.replace(ANCHOR_GRID, section + "\n" + ANCHOR_GRID, 1)
    OUT.write_text(html, encoding="utf-8")

    print("已写出 %s (链 %d 条 / 冷库 %d 条)" % (OUT, len(payload["chains"]), len(load_cold())))
    for c in payload["chains"]:
        print("  %-26s 相关记忆 %3d 条" % (c["id"], c["mem_count"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
