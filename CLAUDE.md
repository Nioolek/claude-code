# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Context

This is a **source snapshot for security research**, not a functional development project. It contains ~1,900 TypeScript files (~512,000 lines) from Claude Code (Anthropic's CLI tool), exposed via a source map leak. There are no build scripts, test configuration, or linting setup in this snapshot.

## Key Entry Points

| File | Purpose |
|------|---------|
| `src/main.tsx` | CLI entry point (Commander.js setup, Ink renderer) |
| `src/screens/REPL.tsx` | Main interactive REPL screen |
| `src/QueryEngine.ts` | Core LLM query engine (streaming, tool-call loops) |
| `src/Tool.ts` | Tool type definitions and base interfaces |
| `src/commands.ts` | Slash command registry |
| `src/tools.ts` | Tool registry |

## Architecture Overview

### Tools (`src/tools/`)
Self-contained modules with input schema, permission model, and execution logic. Key tools: `BashTool`, `FileReadTool`, `FileEditTool`, `GlobTool`, `GrepTool`, `AgentTool`, `MCPTool`, `SkillTool`. Each tool directory contains the implementation and schema.

### Commands (`src/commands/`)
Slash commands with `/` prefix. Examples: `/commit`, `/review`, `/mcp`, `/doctor`, `/memory`, `/skills`, `/tasks`.

### Services (`src/services/`)
External integrations: `api/` (Anthropic API client), `mcp/` (MCP server management), `oauth/`, `lsp/`, `analytics/` (GrowthBook feature flags).

### Bridge (`src/bridge/`)
Bidirectional communication for IDE extensions (VS Code, JetBrains). Handles JWT auth, session management, and message protocol.

### Permission System (`src/hooks/toolPermission/`)
Intercepts every tool invocation with modes: `default`, `plan`, `bypassPermissions`, `auto`.

### Feature Flags
Bun's `bun:bundle` feature() for compile-time dead code elimination. Flags include: `PROACTIVE`, `KAIROS`, `BRIDGE_MODE`, `DAEMON`, `VOICE_MODE`, `COORDINATOR_MODE`.

## Python 开发环境

- **Python 版本**: 3.13.7
- **虚拟环境路径**: `.venv/`（项目根目录）
- **激活方式**: `source .venv/Scripts/activate`（Windows Git Bash）或 `.venv\Scripts\activate`（CMD）
- **所有 Python 开发必须在此虚拟环境中进行**，包括：
  - 运行 Python 脚本：使用 `.venv/Scripts/python.exe` 或先激活环境再运行
  - 安装依赖：先激活环境，再使用 `pip install`
  - 新安装的包会记录到 `requirements.txt`

## Tech Stack

- **Runtime**: Bun (uses `bun:bundle` for feature flags)
- **Language**: TypeScript (strict mode)
- **Terminal UI**: React + Ink
- **CLI Parsing**: Commander.js with `@commander-js/extra-typings`
- **Schema Validation**: Zod v4
- **Search**: ripgrep for GlobTool/GrepTool

## Design Patterns

- **Parallel Prefetch**: MDM settings, keychain reads, and API preconnect run in parallel at startup
- **Lazy Loading**: Heavy modules (OpenTelemetry, gRPC) deferred via dynamic `import()`
- **Agent Swarms**: Sub-agents via `AgentTool`, multi-agent orchestration via `coordinator/`