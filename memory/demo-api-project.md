---
name: demo-api-project
description: 示例链卡——对外接口项目的记忆正文（演示用，可直接删）
metadata:
  node_type: memory
  type: project
  modified: 2026-10-22T12:00:00.000Z
---

# 示例·接口项目

## 拓扑

单机 FastAPI + SQLite，前后端同源。鉴权走 Bearer token。

## 踩过的坑

- 端口写死过一次，换机器就崩 —— 后来一律读 `.env`。
- 参数表只在代码里改了没同步 README，下次对接又问一遍。

## 硬约束

- 测试必须起真服务跑，别 mock 到底。
- 对外字段改动要有迁移说明。

相关：[[demo-docs-project]]
