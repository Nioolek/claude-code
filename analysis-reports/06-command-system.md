# Claude Code Command System Analysis Report

## Module Overview

The command system in Claude Code is a sophisticated architecture for registering, discovering, and executing slash commands. It supports three distinct command types and provides a unified interface for both interactive UI commands and model-invocable skills.

**Core Files:**
- `src/commands.ts` - Central registry and loader
- `src/types/command.ts` - Type definitions
- `src/commands/` - Individual command implementations

---

## Core Components Analysis

### 1. Command Type Definitions

The system defines three command types in `src/types/command.ts`:

#### a) `prompt` Type (PromptCommand)
Commands that expand into prompts sent to the model:

```typescript
type PromptCommand = {
  type: 'prompt'
  progressMessage: string
  contentLength: number
  argNames?: string[]
  allowedTools?: string[]
  model?: string
  source: SettingSource | 'builtin' | 'mcp' | 'plugin' | 'bundled'
  context?: 'inline' | 'fork'  // Execution mode
  agent?: string
  effort?: EffortValue
  paths?: string[] // Conditional skill activation
  getPromptForCommand(args, context): Promise<ContentBlockParam[]>
}
```

#### b) `local` Type (LocalCommand)
Non-interactive commands that execute synchronously:

```typescript
type LocalCommand = {
  type: 'local'
  supportsNonInteractive: boolean
  load: () => Promise<LocalCommandModule>
}
```

#### c) `local-jsx` Type (LocalJSXCommand)
Interactive React-based commands with Ink UI:

```typescript
type LocalJSXCommand = {
  type: 'local-jsx'
  load: () => Promise<LocalJSXCommandModule>
}
```

### 2. Command Base Properties

```typescript
type CommandBase = {
  name: string
  description: string
  aliases?: string[]
  availability?: CommandAvailability[] // Auth gating
  isEnabled?: () => boolean            // Dynamic enablement
  isHidden?: boolean                   // Hide from help
  argumentHint?: string                // Arg hint in UI
  whenToUse?: string                   // Usage guidance
  userInvocable?: boolean              // User can type /cmd
  loadedFrom?: 'skills' | 'plugin' | 'bundled' | 'mcp'
  disableModelInvocation?: boolean     // Block SkillTool access
}
```

---

## Key Command Implementations

### 1. `/commit` - Prompt-Type Command

```typescript
const command = {
  type: 'prompt',
  name: 'commit',
  description: 'Create a git commit',
  allowedTools: ['Bash(git add:*)', 'Bash(git status:*)', 'Bash(git commit:*)'],
  async getPromptForCommand(_args, context) {
    // Dynamic prompt with shell command execution
    const finalContent = await executeShellCommandsInPrompt(promptContent, context, '/commit')
    return [{ type: 'text', text: finalContent }]
  },
}
```

**Key Features:**
- Uses `executeShellCommandsInPrompt()` for dynamic context injection
- Restricts tools via `allowedTools` array

### 2. `/doctor` - Local-JSX Command

```typescript
const doctor: Command = {
  name: 'doctor',
  description: 'Diagnose and verify your Claude Code installation',
  type: 'local-jsx',
  load: () => import('./doctor.js'),
}
```

**Key Pattern:**
- Lazy loading via dynamic import
- React/Ink component rendering
- `onDone` callback for completion

### 3. `/mcp` - Complex Local-JSX Command

```typescript
export async function call(onDone, _context, args?: string) {
  if (args) {
    const parts = args.trim().split(/\s+/)
    if (parts[0] === 'reconnect' && parts[1]) {
      return <MCPReconnect serverName={parts.slice(1).join(' ')} onComplete={onDone} />
    }
  }
  return <MCPSettings onComplete={onDone} />
}
```

### 4. `/clear` - Local-Type Command

```typescript
export const call: LocalCommandCall = async (_, context) => {
  await clearConversation(context)
  return { type: 'text', value: '' }
}
```

---

## Command Discovery and Loading

### Loading Sources

```typescript
const COMMANDS = memoize((): Command[] => [
  addDir, advisor, agents, branch, clear, compact, config, doctor,
  // ... 60+ built-in commands
  ...(feature('PROACTIVE') ? [proactive] : []),
  ...(feature('BRIDGE_MODE') ? [bridge] : []),
])
```

**Key Loading Sources:**
1. **Bundled Skills** - `getBundledSkills()` from `src/skills/bundledSkills.ts`
2. **Plugin Skills** - `getPluginSkills()` from plugin marketplace
3. **Plugin Commands** - `getPluginCommands()` from enabled plugins
4. **Skill Directories** - `getSkillDirCommands()` from `.claude/skills/`
5. **MCP Skills** - From MCP server prompts marked as skills

### Dynamic Skill Discovery

```typescript
export async function discoverSkillDirsForPaths(filePaths: string[], cwd: string): Promise<string[]>
export function activateConditionalSkillsForPaths(filePaths: string[], cwd: string): string[]
```

**Mechanism:**
- Skills with `paths:` frontmatter are conditionally activated
- When model touches matching files, skills become available
- Uses `ignore` library for gitignore-style matching

---

## Command-Skill Relationship

### SkillTool Integration

```typescript
async function getAllCommands(context: ToolUseContext): Promise<Command[]> {
  const mcpSkills = context.getAppState().mcp.commands.filter(
    cmd => cmd.type === 'prompt' && cmd.loadedFrom === 'mcp'
  )
  const localCommands = await getCommands(getProjectRoot())
  return uniqBy([...localCommands, ...mcpSkills], 'name')
}
```

**Execution Modes:**
1. **Inline** - Expands into current conversation
2. **Forked** - Runs in sub-agent with isolated context

---

## Design Highlights

### 1. Lazy Loading Pattern
```typescript
type: 'local-jsx',
load: () => import('./implementation.js')
```
Defers heavy dependencies until command is invoked.

### 2. Feature Flag Integration
```typescript
const bridge = feature('BRIDGE_MODE')
  ? require('./commands/bridge/index.js').default
  : null
```

### 3. Auth Gating
```typescript
export function meetsAvailabilityRequirement(cmd: Command): boolean {
  if (!cmd.availability) return true
  for (const a of cmd.availability) {
    switch (a) {
      case 'claude-ai': if (isClaudeAISubscriber()) return true; break
      case 'console': if (!isClaudeAISubscriber()) return true; break
    }
  }
  return false
}
```

### 4. Remote Mode Safety
```typescript
export const REMOTE_SAFE_COMMANDS: Set<Command> = new Set([
  session, exit, clear, help, theme, color, vim, cost, usage, copy, ...
])
```

---

## File Path Index

### Core Files
| Path | Purpose |
|------|---------|
| `src/commands.ts` | Central command registry |
| `src/types/command.ts` | Type definitions |

### Command Implementations
| Path | Type | Description |
|------|------|-------------|
| `src/commands/commit.ts` | prompt | Git commit creation |
| `src/commands/init.ts` | prompt | CLAUDE.md initialization |
| `src/commands/review.ts` | prompt | PR review |
| `src/commands/doctor/index.ts` | local-jsx | Installation diagnostics |
| `src/commands/mcp/index.ts` | local-jsx | MCP server management |
| `src/commands/memory/index.ts` | local-jsx | Memory file editing |
| `src/commands/skills/index.ts` | local-jsx | Skills menu |
| `src/commands/tasks/index.ts` | local-jsx | Background task management |
| `src/commands/clear/index.ts` | local | Conversation clearing |

### Skill Loading
| Path | Purpose |
|------|---------|
| `src/skills/loadSkillsDir.ts` | Skill directory loading |
| `src/skills/bundledSkills.ts` | Bundled skill registration |

---

## Summary

The command system is a well-architected modular framework that:

1. **Separates concerns** between UI commands (local-jsx), prompt expansion (prompt), and simple operations (local)
2. **Enables extensibility** through plugins, skills directories, and MCP servers
3. **Optimizes performance** with lazy loading and memoization
4. **Enforces security** through permission checks and auth gating
5. **Supports advanced features** like forked execution and conditional skill activation