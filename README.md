# agent-memory-chain

**A file-first memory chain for Claude Code (or any coding agent). No database, no MCP server, no cloud — just Markdown, a JSON registry, and two hooks that cost zero tokens.**

Built for long-running, multi-project work: your agent stops rediscovering the same facts, and the index can't drift because nothing is hand-maintained.

面向长期、多项目的 agent 工作流：**纯文件、人能直接读、hook 零 token 成本**的记忆链。中文说明见下方。

---

## The problem

Agent memory usually fails in one of three ways:

1. **Everything is in one file.** It grows, gets injected in full every turn, and burns tokens on things you didn't ask about.
2. **The index is hand-edited.** Update one fact in three places, forget the fourth, and retrieval quietly breaks.
3. **It's a database.** Powerful, but you can't read it on a plane, diff it in git, or fix it in a text editor.

## Three stores, one source of truth

```
_registry.json          ← single source of truth (keys, aliases, status, next)
        │
        ├──▶ MEMORY.md              generated index — scanned every turn
        │         (_gen_index.py)
        │
        ├──▶ <chain>.md             the actual memory body (readable Markdown)
        │         (_chain_header.py → per-workdir CLAUDE.md)
        │
        └──▶ _memlog.jsonl          append-only operation/session log
                  (_memlog.py)
```

Edit the registry or the memory file, then regenerate. **Never hand-edit `MEMORY.md`** — it will be overwritten, and that's the point.

## Components

| Script | What it does |
|---|---|
| `_gen_index.py` | Rebuilds `MEMORY.md` from `_registry.json` + each file's frontmatter |
| `_chain_header.py` | Writes a per-workdir `CLAUDE.md` chain header (rules/next/assets), never overwrites hand-written files |
| `_recall.py` | `UserPromptSubmit` hook: matches your words against aliases, injects **summaries** (not full text) |
| `_autosave.py` | `Stop` hook: writes this turn's outcome to the cold store — pure stdlib, zero tokens |
| `_memlog.py` | Append-only operation + session log (`list` / `stats`) |
| `_links.py` | Derives the graph edges from `[[wikilinks]]` — one source, no hand-maintained graph |
| `_chain_map.py` | Single-file offline HTML map (domain → chain → assets) |
| `_chain_dash.py` | Interactive dashboard: tripartite graph, timelines, heat, quality ratio |
| `_chain_serve.py` | Local server with action buttons (`--port`, staging area) |
| `_chain_resolve.py` | Resolves which chain the current turn belongs to |
| `_fix_project.py` | Migrates old cold-store `project` values to chain ids |
| `_register_hooks.py` | Installs the hooks into `~/.claude/settings.json` |

## Quick start

```bash
# 1. drop this directory in as your memory dir
cp -r memory ~/.claude/projects/<your-project-slug>/memory

# 2. edit the sample registry into your own chains
$EDITOR memory/_registry.json

# 3. wire the hooks
python memory/_register_hooks.py

# 4. regenerate the index
python memory/_gen_index.py
```

Everything is Python **stdlib only** — no venv, no `pip install`.

## The two hooks

**Recall (`UserPromptSubmit`)** — when you type, it matches your words against every chain's aliases and injects a *summary* (status / next / key pitfalls), never the whole file. That's the cost discipline: full-text injection is how memory systems quietly double your token bill.

**Autosave (`Stop`)** — appends the turn's conclusion to the cold store. Conservative by design: it only writes the raw note, never promotes itself to curated memory. Promotion is a deliberate step you take later.

Both hooks fail silently and never interrupt a turn.

## Design rules that matter

- **`MEMORY.md` is generated.** Hand-edits get clobbered. Change `_registry.json` or the memory file instead.
- **Logs are append-only.** `_memlog.jsonl` never rewrites a line; corrections are new lines. Two writers, no lost updates.
- **Aliases are the retrieval key.** People say "that video thing", the registry knows the slug. Keep aliases short and in your own words.
- **Graph edges are derived.** `[[wikilinks]]` in the memory files *are* the graph. `_links.py` reads them; nothing else stores an edge.
- **Chain headers don't clobber.** `CLAUDE.md` files it writes are marked as auto-generated; a hand-written one is backed up, not replaced.
- **Summaries over bodies.** Everything that gets injected automatically is a few lines, not a file dump.

## How this differs from claude-mem-style tools

Those are typically database + MCP backed, and they're excellent at capture. This is the opposite bet: **plain files you can read, grep, diff and fix**, with generation scripts that keep the index honest. If you want a queryable vector store on top, put one in front of these files — the files stay the record.

## Requirements

Python 3.8+. Nothing else.

## License

MIT

---

# 中文

**给 Claude Code（或任何 coding agent）用的文件优先记忆链。没有数据库、没有 MCP、不连云 —— 就是 Markdown + 一份 JSON 注册表 + 两个零 token 的 hook。**

## 解决什么

1. **全塞一个文件** → 每轮全量进上下文，token 白烧。
2. **索引靠手改** → 一处结论要同步四个地方，漏一处检索就哑。
3. **上数据库** → 强，但你没法用文本编辑器直接读、diff、改。

## 三库分工，一个事实源

| 层 | 是什么 | 谁生成 |
|---|---|---|
| `_registry.json` | 主键 / 别名 / 状态 / 下一步 / 规矩 | 手维护（唯一要手改的） |
| `MEMORY.md` | 每轮扫的索引 | `_gen_index.py` 重生成 |
| `<链>.md` | 记忆正文 | 手写，`_chain_header.py` 生成链头 |
| `_memlog.jsonl` | 操作+会话流水 | `_memlog.py` 追加写 |

**⛔ 别手改 `MEMORY.md`** —— 它会被覆盖，这是设计。

## 两个 hook

- **召回**（`UserPromptSubmit`）：拿你这句话匹配别名，注入**摘要**（状态/下一步/关键坑），不是全文。
- **自动存**（`Stop`）：把本轮结论追加进冷库。保守档，只写原始记录，不自动晋升热库。

两个都是纯标准库、**零 token 成本**，失败静默退出，永不打断会话。

## 几条要守住的规矩

- 索引是生成物，改注册表和正文，别改索引
- 日志只追加不原地改（两个写方不会互相覆盖）
- 别名是检索的钥匙，用你自己的话记
- 图的边从 `[[双链]]` 推导，别另存一份
- 链头文件带自动生成标记，不覆盖手写文件
- **自动注入的永远是摘要，不是全文**

## 和 claude-mem 那类的区别

那类是数据库 + MCP，强在捕获；这套反过来赌：**文件能直接读、grep、diff、手改**，生成脚本负责让索引不失真。要向量检索就在文件前面加一层，文件本身仍是记录本。

## 依赖

Python 3.8+，零第三方依赖。
