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