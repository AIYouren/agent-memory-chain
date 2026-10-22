#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""仪表板布局体检 —— 量 DOM, 不靠 vision。

为什么单独一个脚本: 我们吃过两次亏 —— 同一张截图, vision 先说「布局和谐统一、没有明显问题」,
把 6 个 KPI 磁贴说成 4 个; 又说某处对比度过低(实际 12:1)。**像素/DOM 才准。**
把上轮手写的一次性探针固化成这儿一个入口, 别再每次现写。

查什么(全是量出来的, 不是猜的):
  1. 溢出    —— scrollWidth > clientWidth 且 overflow:visible 的非 SVG 元素
  2. 状态 pill 溢出 —— pill 右边界越过它该待的那一列(历史上溢出 143px, 压到时间轴上)
  3. 栅格撑高 —— auto-fit 栅格里最长的卡把同排全部撑高的幅度
  4. 页高分段 —— header / 链区块 / 上游面板各占多少
  5. 折叠可展开 —— 被 -webkit-line-clamp 钳住却**没长展开按钮**的块(静默截断, 比不改还糟)

跑法:
  PYTHONUTF8=1 python _dash_check.py          # 人看的报告
  PYTHONUTF8=1 python _dash_check.py --json   # 机器读
退出码: 有硬伤(溢出/pill 越界/钳了没按钮)则 1。

依赖: playwright(系统 python 有) + 已生成 ~/.deep-memory/memory-dashboard.html
"""
import io
import json
import os
import sys
from pathlib import Path

DASH = Path(os.path.expanduser("~/.deep-memory/memory-dashboard.html"))

JS = r"""
() => {
  const out = {doc: document.documentElement.scrollHeight, overflow: [], pill: [],
               grid: [], clamp: [], sec: []};

  // 1. 溢出 —— SVG 的 clientWidth 对 <text> 无意义, 一律跳过(会全是误报)
  document.querySelectorAll('*').forEach(el => {
    if (el.ownerSVGElement || el.tagName === 'svg') return;
    if (el.children.length || el.clientWidth <= 0) return;
    if (getComputedStyle(el).overflow !== 'visible') return;
    if (el.scrollWidth > el.clientWidth + 2) {
      out.overflow.push({tag: el.tagName.toLowerCase(),
        cls: String(el.className || '').slice(0, 24),
        sw: el.scrollWidth, cw: el.clientWidth,
        txt: (el.textContent || '').trim().slice(0, 30)});
    }
  });

  // 2. 状态 pill 越界 —— 只看链卡头部与 rail 行头两种容器
  document.querySelectorAll('.dm-cc-head, .dm-rail-head').forEach(h => {
    const p = h.querySelector('.dm-pill');
    if (!p) return;
    const hr = h.getBoundingClientRect(), pr = p.getBoundingClientRect();
    if (pr.right - hr.right > 1) {
      out.pill.push({where: h.className, spill: Math.round(pr.right - hr.right),
        txt: p.textContent.trim().slice(0, 34)});
    }
  });

  // 3. 栅格撑高 —— 同排里最高与最矮的差
  ['.dm-chain-grid', '#dm-cf .dm-cf-cols'].forEach(sel => {
    const g = document.querySelector(sel);
    if (!g) return;
    const kids = Array.from(g.children).filter(k => k.getBoundingClientRect().height > 2);
    if (kids.length < 2) return;
    const hs = kids.map(k => Math.round(k.getBoundingClientRect().height));
    const rows = Math.max.apply(null, hs) - Math.min.apply(null, hs);
    out.grid.push({sel, n: kids.length, min: Math.min.apply(null, hs),
      max: Math.max.apply(null, hs), spread: rows});
  });

  // 4. 页高分段
  [['header', 'body > header'], ['链区块', '#dm-chains'],
   ['上游面板', '.grid']].forEach(([label, sel]) => {
    const e = document.querySelector(sel);
    if (e) out.sec.push({label, h: Math.round(e.getBoundingClientRect().height)});
  });

  // 5. 钳了却没按钮 —— 带 clamp 量不出自然高度, 得先放开
  document.querySelectorAll('.dm-chain-card').forEach((card, i) => {
    const bar = card.querySelector('.dm-cc-bar');
    const btns = bar ? bar.textContent : '';
    card.querySelectorAll('.dm-cc-next').forEach(node => {
      node.classList.add('is-open');
      const full = node.scrollHeight;
      node.classList.remove('is-open');
      if (full > node.clientHeight + 4 && btns.indexOf('展开') < 0) {
        out.clamp.push({card: i, txt: (node.textContent || '').trim().slice(0, 30)});
      }
    });
  });
  return out;
}
"""


def run():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1600, "height": 1000})
        pg.goto(DASH.as_uri())
        pg.wait_for_timeout(3500)
        r = pg.evaluate(JS)
        b.close()
    return r


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if not DASH.exists():
        print("找不到 %s —— 先跑 _chain_dash.py 生成" % DASH)
        return 1
    r = run()

    if "--json" in sys.argv:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        print("页高 %dpx" % r["doc"])
        for s in r["sec"]:
            print("   %-8s %5dpx" % (s["label"], s["h"]))
        print("\n栅格撑高:")
        for g in r["grid"]:
            note = "⚠ 同排 %d 项被最长的撑到 %dpx(最短 %d)" % (g["n"], g["max"], g["min"]) \
                if g["spread"] > 260 else "ok"
            print("   %-22s %s" % (g["sel"], note))
        print("\npill 越界: %d 处" % len(r["pill"]))
        for x in r["pill"]:
            print("   %s 溢出 %dpx | %s" % (x["where"], x["spill"], x["txt"]))
        print("\n溢出: %d 处" % len(r["overflow"]))
        for x in r["overflow"][:10]:
            print("   %s .%s  %d>%d | %s" % (x["tag"], x["cls"], x["sw"], x["cw"], x["txt"]))
        print("\n钳了没长展开按钮: %d 处" % len(r["clamp"]))
        for x in r["clamp"]:
            print("   card#%d %s" % (x["card"], x["txt"]))

    bad = len(r["pill"]) + len(r["overflow"]) + len(r["clamp"])
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
