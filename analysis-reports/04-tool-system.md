# Claude Code Tool System Analysis Report

## Module Overview

The Claude Code tool system is a sophisticated, extensible architecture for defining, registering, and executing tools that the AI can use to interact with the environment. The system is built around a strong type system with Zod schemas, a factory pattern for tool creation, and a layered permission model.

**Core Files:**
- `src/Tool.ts` - Type definitions and buildTool factory (793 lines)
- `src/tools.ts` - Tool registry and assembly logic (390 lines)
- `src/constants/tools.ts` - Tool availability constants
- `src/types/permissions.ts` - Permission type definitions

---

## Core Components Analysis

### 1. Tool Type Definition (`src/Tool.ts`)

The `Tool` type is the central interface that every tool must implement:

```typescript
type Tool<Input, Output, P extends ToolProgressData> = {
  // Core Identity
  name: string
  aliases?: string[]
  searchHint?: string

  // Schema Definition
  inputSchema: AnyObject
  inputJSONSchema?: ToolInputJSONSchema
  outputSchema?: z.ZodType<unknown>

  // Execution
  call(args, context, canUseTool, parentMessage, onProgress): Promise<ToolResult<Output>>

  // Description & UI
  description(input, options): Promise<string>
  prompt(options): Promise<string>
  userFacingName(input): string

  // Permission & Validation
  validateInput?(input, context): Promise<ValidationResult>
  checkPermissions(input, context): Promise<PermissionResult>
  preparePermissionMatcher?(input): Promise<(pattern: string) => boolean>

  // Behavioral Properties
  isEnabled(): boolean
  isConcurrencySafe(input): boolean
  isReadOnly(input): boolean
  isDestructive?(input): boolean
  interruptBehavior?(): 'cancel' | 'block'

  // Rendering
  renderToolUseMessage(input, options): React.ReactNode
  renderToolResultMessage(content, progressMessages, options): React.ReactNode
  mapToolResultToToolResultBlockParam(content, toolUseID): ToolResultBlockParam
}
```

### 2. buildTool Factory Function

The `buildTool` function provides safe defaults for commonly omitted methods:

```typescript
const TOOL_DEFAULTS = {
  isEnabled: () => true,
  isConcurrencySafe: (_input?: unknown) => false,  // Fail-closed: assume not safe
  isReadOnly: (_input?: unknown) => false,          // Fail-closed: assume writes
  isDestructive: (_input?: unknown) => false,
  checkPermissions: (input, _ctx) =>
    Promise.resolve({ behavior: 'allow', updatedInput: input }),
  toAutoClassifierInput: (_input?: unknown) => '',
  userFacingName: () => '',
}

export function buildTool<D extends AnyToolDef>(def: D): BuiltTool<D> {
  return {
    ...TOOL_DEFAULTS,
    userFacingName: () => def.name,
    ...def,
  } as BuiltTool<D>
}
```

### 3. Tool Registration (`src/tools.ts`)

```typescript
export function getAllBaseTools(): Tools {
  return [
    AgentTool,
    TaskOutputTool,
    BashTool,
    ...(hasEmbeddedSearchTools() ? [] : [GlobTool, GrepTool]),
    ExitPlanModeV2Tool,
    FileReadTool,
    FileEditTool,
    FileWriteTool,
    // ... conditional tools based on feature flags
    ...(isTodoV2Enabled() ? [TaskCreateTool, TaskGetTool, TaskUpdateTool, TaskListTool] : []),
    ...(process.env.USER_TYPE === 'ant' ? [ConfigTool, TungstenTool] : []),
  ]
}
```

**Conditional Tool Loading:**
- Feature flags conditionally include tools
- Environment variables enable internal-only tools
- Dead code elimination via Bun's `bun:bundle`

### 4. Tool Filtering and Permission Integration

```typescript
type ToolPermissionContext = {
  mode: PermissionMode
  additionalWorkingDirectories: Map<string, AdditionalWorkingDirectory>
  alwaysAllowRules: ToolPermissionRulesBySource
  alwaysDenyRules: ToolPermissionRulesBySource
  alwaysAskRules: ToolPermissionRulesBySource
  isBypassPermissionsModeAvailable: boolean
  isAutoModeAvailable?: boolean
}
```

---

## Design Highlights

### 1. Fail-Closed Defaults

The `TOOL_DEFAULTS` object uses conservative defaults:
- `isConcurrencySafe` defaults to `false` - assume unsafe
- `isReadOnly` defaults to `false` - assume writes

### 2. Type-Safe Tool Definition

```typescript
type DefaultableToolKeys =
  | 'isEnabled'
  | 'isConcurrencySafe'
  | 'isReadOnly'
  | 'isDestructive'
  | 'checkPermissions'
  | 'toAutoClassifierInput'
  | 'userFacingName'

type ToolDef<Input, Output, P> =
  Omit<Tool<Input, Output, P>, DefaultableToolKeys> &
  Partial<Pick<Tool<Input, Output, P>, DefaultableToolKeys>>
```

### 3. MCP Tool Integration

MCP tools are identified by the `isMcp` flag and `mcpInfo` metadata.

### 4. Lazy Schema Pattern

```typescript
const inputSchema = lazySchema(() =>
  z.strictObject({
    file_path: z.string().describe('The absolute path to the file to read'),
  })
)
```

### 5. Tool Pool Assembly

```typescript
export function assembleToolPool(
  permissionContext: ToolPermissionContext,
  mcpTools: Tools,
): Tools {
  const builtInTools = getTools(permissionContext)
  const allowedMcpTools = filterToolsByDenyRules(mcpTools, permissionContext)
  return uniqBy(
    [...builtInTools].sort(byName).concat(allowedMcpTools.sort(byName)),
    'name',
  )
}
```

---

## Module Interactions

```
                    ┌──────────────────────────────────────────────┐
                    │                  QueryEngine                  │
                    └──────────────────────┬───────────────────────┘
                                           │
                                           ▼
┌────────────────────┐      ┌──────────────────────────────────────┐
│    commands.ts     │      │              tools.ts                 │
│  (Slash Commands)  │      │    (Tool Registry & Assembly)         │
└────────────────────┘      └──────────────────────┬───────────────┘
                                                    │
                    ┌───────────────────────────────┼───────────────────┐
                    │                               │                   │
                    ▼                               ▼                   ▼
          ┌─────────────────┐           ┌─────────────────┐   ┌─────────────────┐
          │    Tool.ts      │           │  toolExecution  │   │ useCanUseTool   │
          │ (Type Defs)     │           │ (Execution)     │   │ (Permission)    │
          └────────┬────────┘           └────────┬────────┘   └────────┬────────┘
                   │                             │                     │
                   ▼                             ▼                     ▼
    ┌──────────────────────────────────────────────────────────────────────────┐
    │                         Individual Tools                                  │
    │  BashTool, FileReadTool, FileEditTool, GlobTool, GrepTool, AgentTool... │
    └──────────────────────────────────────────────────────────────────────────┘
```

---

## File Path Index

| Category | File Path | Purpose |
|----------|-----------|---------|
| **Core Types** | `src/Tool.ts` | Tool interface, buildTool factory |
| **Registry** | `src/tools.ts` | getAllBaseTools, assembleToolPool |
| **Constants** | `src/constants/tools.ts` | ALL_AGENT_DISALLOWED_TOOLS |
| **Permission Types** | `src/types/permissions.ts` | PermissionMode, PermissionResult |
| **Permission Logic** | `src/utils/permissions/permissions.ts` | hasPermissionsToUseTool |
| **Permission Hook** | `src/hooks/useCanUseTool.tsx` | useCanUseTool hook |
| **Tool Execution** | `src/services/tools/toolExecution.ts` | executeTool |

---

## Summary

The Claude Code tool system demonstrates excellent software engineering practices:

1. **Strong Type Safety**: TypeScript generics and Zod schemas ensure end-to-end type consistency
2. **Extensibility**: The buildTool factory makes it easy to define new tools with minimal boilerplate
3. **Security**: Multi-layered permission system with fail-closed defaults
4. **Performance**: Lazy schema construction and compile-time dead code elimination
5. **Modularity**: Clear separation between tool definition, registration, execution, and permissions