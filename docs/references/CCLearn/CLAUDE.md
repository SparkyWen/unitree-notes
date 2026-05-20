# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repository Is

This is the extracted source of `@anthropic-ai/claude-code@2.1.88`, obtained from the published npm package's source map (`cli.js.map`). The `source/` tree is for **reading and studying only** — it cannot be rebuilt (missing build deps, Bun bundler APIs, tsconfig, etc.). The bundled `cli.js` is the actual executable.

## Running

```sh
node cli.js --version          # 2.1.88
node cli.js --help             # all options
node cli.js -p "hello world"   # non-interactive one-shot
node cli.js                    # interactive REPL
```

There are no build, lint, or test commands — this is an extracted read-only source tree, not a development environment.

## Architecture Overview

### Entry Points

- **`source/src/entrypoints/cli.tsx`** — Minimal bootstrap with fast-paths (`--version`, daemon workers, bridge mode). Uses dynamic imports to minimize startup time.
- **`source/src/main.tsx`** (~4700 lines) — The real startup: auth, configs, feature gates (GrowthBook), telemetry, AppState creation, then launches the REPL.
- **`source/src/entrypoints/mcp.ts`** — MCP (Model Context Protocol) server mode entry.

### Core Query Engine

The conversation loop lives in:
- **`query.ts`** (~1700 lines) — Turn-by-turn processing: assembles tool pool, builds system prompt, normalizes messages for the API, streams responses, dispatches tool calls, collects results, loops until no more tool_use blocks.
- **`QueryEngine.ts`** — Higher-level orchestration for SDK/remote modes.
- **`Tool.ts`** — Tool type definitions and dispatch.

### Tools System (~40+ tools)

Each tool exports `buildTool()` with a name, Zod schema, and execute function. Located under `source/src/tools/`, one directory per tool.

Key categories:
- **File ops:** FileReadTool, FileEditTool, FileWriteTool, GlobTool, GrepTool
- **Execution:** BashTool, PowerShellTool, AgentTool
- **External:** WebSearchTool, WebFetchTool, MCPTool, LSPTool
- **Interactive:** AskUserQuestionTool, SendMessageTool
- **System:** TaskCreateTool, EnterWorktreeTool, EnterPlanModeTool, SkillTool

### Commands System (~50+ slash commands)

Each command is a directory under `source/src/commands/` with an `index.ts` exporting a `Command` object (type: `'prompt'`, `'local'`, or `'nonInteractive'`). The registry in `commands.ts` merges built-in, skill, and plugin commands.

### Agent / Multi-Agent System

- **`tools/AgentTool/AgentTool.tsx`** — Spawns subagents (general-purpose, plan, explore, etc.).
- **`tools/AgentTool/forkSubagent.ts`** — Creates isolated git worktrees for agent work.
- **`tasks/LocalAgentTask/`** — In-process background agent execution.
- **`tasks/RemoteAgentTask/`** — Cloud-based agent execution.
- **`coordinator/coordinatorMode.ts`** — Multi-worker orchestration (spawns concurrent agents with restricted tool sets).

### Bridge / Remote Control

Allows a local machine to be controlled by cloud Claude (`claude rc`):
- **`bridge/bridgeMain.ts`** — Entry: polls for sessions, spawns runners.
- **`bridge/replBridge.ts`** — Bridges local REPL to cloud API.
- **`bridge/sessionRunner.ts`** — Spawns sandboxed `claude --bridge-worker` subprocesses.

### State & UI

- **`state/AppStateStore.tsx`** — Zustand-style store (messages, session, tools, theme, etc.), shared via React Context.
- **`screens/REPL.tsx`** — Main interactive terminal screen.
- **`ink/`** — Custom fork of the Ink terminal rendering library (DOM emulation, focus management).
- **`components/`** — React/Ink UI components (message rendering, notifications, design system).

### Permissions & Hooks

- **`utils/permissions/`** — Three modes: `default` (ask), `auto` (auto-allow), `bypass`. Per-tool allow/deny rules.
- **Hooks** (`hooks/`, `bootstrap/state.ts`) — Pre/post compact, prompt customization, tool call validation. Configured in `~/.claude/hooks.json` or via API.

### Services

Under `source/src/services/`:
- **MCP** — Server discovery, connection lifecycle, tool wrapping (`MCPServerConnection.ts`, `officialRegistry.ts`).
- **Compact** — Message compression when approaching context limits.
- **OAuth** — Authentication flows.
- **Plugins** — Plugin loading and validation.
- **Policy limits** — Rate/usage controls.

### Skills

Under `source/src/skills/`: Dynamic and bundled skills (batch, loop, simplify, etc.) loaded at runtime via `loadSkillsDir.ts`.

### Context & Prompts

- **`context.ts`** — Builds system context (git status, workspace info, CLAUDE.md memory injection).
- **`constants/prompts.ts`** — System prompt generation.
- **`memdir/`** — CLAUDE.md memory file management and path resolution.

### Key Data Flow

```
User input → query.ts → API request (messages + system prompt + tools)
  → Stream response → parse tool_use blocks
  → Permission check → hook validation → tool execution
  → Tool result → append to messages → back to API if more tool_use
  → Display response → persist session → next turn
```
