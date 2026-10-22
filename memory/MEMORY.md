# Memory Index

> **这张表由 `_gen_index.py` 自动生成，别手改。**
> 改内容去改 `_registry.json`(主键/别名/下一步)或对应的记忆文件，跑
> `PYTHONUTF8=1 python _gen_index.py` 重生成。三库对照见 `_registry.json` 的 `dm_crosswalk`。

**三库分工**：`MEMORY.md`(本表,每轮全量注入) → 记忆文件(主档) → `_registry.json`(主键) ；
deep-memory 热库/冷库是同一批事的压缩副本，对照在 `dm_crosswalk`；works 侧的状态在 `任务台账.md`。

## 0. 你的叫法 → 查哪条

> 你说话用的词常常和记忆的 slug 对不上，先在这里对一眼。

| 叫法 | 叫法 | 叫法 | 叫法 | 叫法 |
|---|---|---|---|---|
| 写稿 → `demo-docs-project` | 后端 → `demo-api-project` | 接口 → `demo-api-project` | 文档 → `demo-docs-project` | api → `demo-api-project` |
| 写文档 → `demo-docs-project` | docs → `demo-docs-project` | api项目 → `demo-api-project` | demo-api → `demo-api-project` |  |

## 1. ★ 在跑的活（先看这里，每条都带下一步）

### 示例·接口项目
- `demo-api-project` → `demo-api-project.md` ｜ 进行中·鉴权已通 ｜ `C:\work\demo-api` 脚本 `server/app.py | tests/`
- 成品：对外 HTTP 接口 + 测试
- 下一步：①补限流；②把参数表同步进 README

### 示例·文档项目
- `demo-docs-project` → `demo-docs-project.md` ｜ 进行中·第 3 篇待审 ｜ `C:\work\demo-docs` 脚本 `build.py`
- 成品：发布用长文 + 配图
- 下一步：①等用户改第 3 篇；②补图注

## 2. 全量索引（按域，只列 slug）

> 描述在各记忆文件的 frontmatter 里，这里只给路径。要判断相关性就直接 Read 那个文件。

### 示例域（2）
- `demo-api-project` `demo-docs-project`

## 3. 完整性检查

- ✅ 无孤儿记忆
- ✅ 无死链
- 记忆文件 2 个 / 主键 2 个 / 域 1 个

## 4. 日志表

> 记忆库的**过程**流水（A=操作 B=会话），最近 10 条，全量见 `_memlog.py list`。

| 时间 | 类 | 动作 | 对象 | 说明 |
|---|---|---|---|---|
| 10-22 18:39 | A | 重建 MEMORY.md | MEMORY.md | 2 主键 / 1 域 |
| 10-22 18:38 | A | 重建 MEMORY.md | MEMORY.md | 2 主键 / 1 域 |
