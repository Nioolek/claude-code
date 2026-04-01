# Claude Code Core Tools Analysis Report

## Module Overview

Claude Code implements five foundational tools for file system interaction and command execution. These tools are built using a consistent architecture pattern with Zod v4 schema validation, permission hooks, and React-based UI rendering.

| Tool | Purpose | Key File |
|------|---------|----------|
| **BashTool** | Shell command execution with sandboxing | `src/tools/BashTool/BashTool.tsx` |
| **FileReadTool** | Multi-format file reading | `src/tools/FileReadTool/FileReadTool.ts` |
| **FileEditTool** | In-place string replacement editing | `src/tools/FileEditTool/FileEditTool.ts` |
| **GlobTool** | File pattern matching | `src/tools/GlobTool/GlobTool.ts` |
| **GrepTool** | Content search using ripgrep | `src/tools/GrepTool/GrepTool.ts` |

---

## 1. BashTool - Shell Command Execution

### Input Schema

```typescript
z.strictObject({
  command: z.string().describe('The command to execute'),
  timeout: z.number().optional().describe('Optional timeout in milliseconds'),
  description: z.string().optional().describe('Clear, concise description'),
  run_in_background: z.boolean().optional().describe('Run in background'),
  dangerouslyDisableSandbox: z.boolean().optional().describe('Override sandbox'),
})
```

### Permission Model

**Multi-layered permission system:**

1. **Mode-based validation** (`modeValidation.ts`):
   - `acceptEdits` mode auto-allows filesystem commands: `mkdir`, `touch`, `rm`, `rmdir`, `mv`, `cp`

2. **Read-only constraint checking** (`readOnlyValidation.ts`):
   - Validates commands against read-only command lists for git, gh, docker
   - Compound commands (pipes, &&, ||) analyzed per-segment

3. **Sandbox system** (`shouldUseSandbox.ts`):
   - Checks `SandboxManager.isSandboxingEnabled()`
   - Respects `dangerouslyDisableSandbox` flag
   - Supports wildcard patterns (`bazel:*`), exact matches, and prefix patterns

### Execution Highlights

- **Background tasks**: Commands can run with `run_in_background: true`
- **Timeout handling**: Default 2 minutes, max 10 minutes
- **Progress streaming**: Shows output progressively after 2 seconds
- **Large output handling**: Persists to `tool-results` directory when > 30KB

---

## 2. FileReadTool - File Reading

### Input Schema

```typescript
z.strictObject({
  file_path: z.string().describe('The absolute path to the file to read'),
  offset: z.number().int().nonnegative().optional().describe('Start line'),
  limit: z.number().int().positive().optional().describe('Number of lines'),
  pages: z.string().optional().describe('Page range for PDF files'),
})
```

### Output Types (Discriminated Union)

```typescript
type Output =
  | { type: 'text'; file: { filePath, content, numLines } }
  | { type: 'image'; file: { base64, type, dimensions } }
  | { type: 'notebook'; file: { filePath, cells } }
  | { type: 'pdf'; file: { filePath, base64 } }
  | { type: 'file_unchanged'; file: { filePath } }
```

### File Type Handlers

| Type | Handler | Notes |
|------|---------|-------|
| Text | `readFileInRange()` | Line-numbered output, offset/limit |
| Image | `readImageWithTokenBudget()` | Auto-resize, token-based compression |
| PDF | `readPDF()` | Native PDF support |
| Notebook | `readNotebook()` | Jupyter .ipynb cell parsing |

### Deduplication System

```typescript
// File unchanged detection - returns stub instead of re-reading
if (existingState && !existingState.isPartialView) {
  const rangeMatch = existingState.offset === offset && existingState.limit === limit;
  if (rangeMatch && mtimeMs === existingState.timestamp) {
    return { data: { type: 'file_unchanged', file: { filePath } } };
  }
}
```

---

## 3. FileEditTool - File Editing

### Input Schema

```typescript
z.strictObject({
  file_path: z.string().describe('The absolute path to the file to modify'),
  old_string: z.string().describe('The text to replace'),
  new_string: z.string().describe('The replacement text'),
  replace_all: z.boolean().default(false).optional().describe('Replace all occurrences'),
})
```

### Permission Model

- **Write permission check**: `checkWritePermissionForTool()`
- **Read-first requirement**: File must be in `readFileState` before editing
- **Staleness detection**: Compares mtime with last read timestamp
- **Team memory secret guard**: Blocks credential introduction

### Quote Normalization

```typescript
// utils.ts - Handles curly quotes normalization
export function findActualString(fileContent: string, searchString: string): string | null {
  if (fileContent.includes(searchString)) return searchString;
  const normalizedSearch = normalizeQuotes(searchString);
  const normalizedFile = normalizeQuotes(fileContent);
  // Returns actual string from file matching normalized pattern
}
```

### Execution Flow

1. **Pre-edit backup**: `fileHistoryTrackEdit()` for undo support
2. **Atomic read-modify-write**: Minimal async between staleness check and write
3. **LSP notification**: `didChange` and `didSave` events
4. **VSCode notification**: `notifyVscodeFileUpdated()` for diff view
5. **State update**: Updates `readFileState` with new content

---

## 4. GlobTool - File Pattern Matching

### Input Schema

```typescript
z.strictObject({
  pattern: z.string().describe('The glob pattern to match files against'),
  path: z.string().optional().describe('The directory to search in'),
})
```

### Output Schema

```typescript
z.object({
  durationMs: z.number().describe('Time taken in milliseconds'),
  numFiles: z.number().describe('Total number of files found'),
  filenames: z.array(z.string()).describe('Array of matching file paths'),
  truncated: z.boolean().describe('Whether results were truncated'),
})
```

### Execution

- Uses internal `glob()` function (wraps fast-glob or bfs)
- Results sorted by modification time
- Default limit: 100 files
- Paths relativized under CWD to save tokens

---

## 5. GrepTool - Content Search

### Input Schema

```typescript
z.strictObject({
  pattern: z.string().describe('The regular expression pattern to search for'),
  path: z.string().optional().describe('File or directory to search in'),
  glob: z.string().optional().describe('Glob pattern to filter files'),
  output_mode: z.enum(['content', 'files_with_matches', 'count']).optional(),
  '-B': z.number().optional().describe('Lines before match'),
  '-A': z.number().optional().describe('Lines after match'),
  '-C': z.number().optional().describe('Context lines'),
  '-n': z.boolean().optional().describe('Show line numbers'),
  '-i': z.boolean().optional().describe('Case insensitive'),
  type: z.string().optional().describe('File type to search'),
  head_limit: z.number().optional().describe('Limit output to first N'),
  offset: z.number().optional().describe('Skip first N entries'),
  multiline: z.boolean().optional().describe('Enable multiline mode'),
})
```

### Output Modes

| Mode | Description | Ripgrep Flag |
|------|-------------|--------------|
| `files_with_matches` | File paths only (default) | `-l` |
| `content` | Matching lines with context | default |
| `count` | Match counts per file | `-c` |

### Execution

- Wraps ripgrep via `ripGrep()` function
- Auto-excludes VCS directories: `.git`, `.svn`, `.hg`
- Max column width: 500 chars
- Default head_limit: 250

---

## Design Highlights Comparison

| Aspect | BashTool | FileReadTool | FileEditTool | GlobTool | GrepTool |
|--------|----------|--------------|--------------|----------|----------|
| **Sandboxing** | Full sandbox system | N/A | N/A | N/A | N/A |
| **Background execution** | Yes | No | No | No | No |
| **Token limiting** | Output truncation | 25K token cap | N/A | 100 file limit | 250 result limit |
| **Permission hooks** | Multi-layer | Read-only | Read-first + write | Read-only | Read-only |
| **Output formats** | text/image | text/image/pdf/notebook | patch diff | file list | content/files/count |
| **Pagination** | Persisted output | offset/limit | N/A | truncated flag | head_limit/offset |

---

## File Path Index

### BashTool
- `src/tools/BashTool/BashTool.tsx` - Main implementation
- `src/tools/BashTool/bashPermissions.ts` - Permission rules
- `src/tools/BashTool/shouldUseSandbox.ts` - Sandbox decision logic
- `src/tools/BashTool/modeValidation.ts` - Mode-based permissions
- `src/tools/BashTool/readOnlyValidation.ts` - Read-only command detection

### FileReadTool
- `src/tools/FileReadTool/FileReadTool.ts` - Main implementation
- `src/tools/FileReadTool/limits.ts` - Token/size limits
- `src/tools/FileReadTool/imageProcessor.ts` - Sharp integration

### FileEditTool
- `src/tools/FileEditTool/FileEditTool.ts` - Main implementation
- `src/tools/FileEditTool/utils.ts` - Quote normalization, patch generation

### GlobTool
- `src/tools/GlobTool/GlobTool.ts` - Main implementation

### GrepTool
- `src/tools/GrepTool/GrepTool.ts` - Main implementation

---

## Key Architectural Patterns

1. **Lazy Schema Loading**: All tools use `lazySchema()` to defer Zod schema construction
2. **Permission Matcher Pattern**: `preparePermissionMatcher()` enables hook allowlists with wildcard matching
3. **Result Persistence**: Large outputs persisted to `tool-results` directory
4. **Semantic Numbers/Booleans**: `semanticNumber()` and `semanticBoolean()` preprocess inputs
5. **Feature Flags**: Bun's `feature()` for compile-time dead code elimination