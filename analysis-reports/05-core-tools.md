# Claude Code 核心工具分析报告

## 模块概述

核心工具是 Claude Code 的「五大金刚」，就像**装修队的五件套工具**——每件工具都有明确的用途、安全规程和操作方法。这五个工具构成了 AI 与外部世界交互的基础设施。

### 五大核心工具

| 工具 | 功能类比 | 核心职责 | 关键文件 |
|------|----------|----------|----------|
| **BashTool** | 电钻/电锯 | Shell 命令执行，支持沙箱隔离 | `src/tools/BashTool/BashTool.tsx` |
| **FileReadTool** | 放大镜 | 多格式文件读取（文本/图片/PDF/Notebook） | `src/tools/FileReadTool/FileReadTool.ts` |
| **FileEditTool** | 精密刻刀 | 文件内容精确替换编辑 | `src/tools/FileEditTool/FileEditTool.ts` |
| **GlobTool** | 文件探测器 | 文件名模式匹配搜索 | `src/tools/GlobTool/GlobTool.ts` |
| **GrepTool** | 内容扫描仪 | 文件内容正则搜索（基于 ripgrep） | `src/tools/GrepTool/GrepTool.ts` |

### 生活化类比

想象你是一个装修队的队长，需要完成各种任务：

| 场景 | 使用工具 | 说明 |
|------|----------|------|
| 「帮我看看这个文件写了什么」 | FileReadTool | 用放大镜仔细查看 |
| 「找出所有 `.ts` 文件」 | GlobTool | 用探测器扫描整个工地 |
| 「搜索哪里用到了 `useState`」 | GrepTool | 用扫描仪精确定位 |
| 「把这里的 `foo` 改成 `bar`」 | FileEditTool | 用刻刀精确修改 |
| 「运行 `npm test`」 | BashTool | 用电动工具执行任务 |

---

## 1. BashTool - Shell 命令执行工具

### 工具角色

BashTool 是最强大的工具，就像**一把多功能电钻**——可以执行任意 Shell 命令，但同时也需要最严格的安全控制。

### 输入 Schema

```typescript
z.strictObject({
  command: z.string().describe('要执行的命令'),
  timeout: z.number().optional().describe('超时时间（毫秒）'),
  description: z.string().optional().describe('命令用途说明'),
  run_in_background: z.boolean().optional().describe('是否后台运行'),
  dangerouslyDisableSandbox: z.boolean().optional().describe('禁用沙箱（危险）'),
})
```

### 多层权限模型

BashTool 采用**洋葱式权限模型**，每一层都进行独立检查：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      BashTool 权限检查流程                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────────────────────────┐                               │
│  │ Layer 1: 模式验证 (modeValidation.ts)    │                               │
│  │                                          │                               │
│  │ • acceptEdits 模式：自动允许文件系统命令  │                               │
│  │   (mkdir, touch, rm, mv, cp)            │                               │
│  │ • plan 模式：只读命令检查                │                               │
│  └──────────────────────────────────────────┘                               │
│         │                                                                    │
│         ▼                                                                    │
│  ┌──────────────────────────────────────────┐                               │
│  │ Layer 2: 只读约束 (readOnlyValidation.ts) │                               │
│  │                                          │                               │
│  │ • git/gh/docker 只读命令白名单            │                               │
│  │ • 复合命令逐段分析 (管道 && ||)          │                               │
│  │ • 检测破坏性操作 (delete, push --force)  │                               │
│  └──────────────────────────────────────────┘                               │
│         │                                                                    │
│         ▼                                                                    │
│  ┌──────────────────────────────────────────┐                               │
│  │ Layer 3: 沙箱系统 (shouldUseSandbox.ts)   │                               │
│  │                                          │                               │
│  │ • SandboxManager.isSandboxingEnabled()  │                               │
│  │ • 通配符模式匹配 (bazel:*)               │                               │
│  │ • 前缀模式匹配 (npm *)                   │                               │
│  │ • 精确匹配 (git status)                  │                               │
│  └──────────────────────────────────────────┘                               │
│         │                                                                    │
│         ▼                                                                    │
│  ┌──────────────────────────────────────────┐                               │
│  │ Layer 4: 用户确认 (canUseTool)            │                               │
│  │                                          │                               │
│  │ • 弹出权限对话框                          │                               │
│  │ • 支持临时/永久允许                       │                               │
│  │ • 显示命令预览和风险评估                  │                               │
│  └──────────────────────────────────────────┘                               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 执行特性

| 特性 | 说明 | 配置值 |
|------|------|--------|
| **后台执行** | `run_in_background: true` 启用 | 用于长时间任务 |
| **超时控制** | 默认 2 分钟，最大 10 分钟 | 防止命令卡死 |
| **进度流式** | 2 秒后开始显示输出 | 实时反馈 |
| **大输出处理** | 超过 30KB 持久化到磁盘 | 避免上下文膨胀 |
| **沙箱隔离** | 限制命令执行范围 | 安全防护 |

### 命令分类（UI 折叠显示）

```typescript
// 搜索命令（可折叠）
const BASH_SEARCH_COMMANDS = new Set(['find', 'grep', 'rg', 'ag', 'ack', 'locate'])

// 读取命令（可折叠）
const BASH_READ_COMMANDS = new Set(['cat', 'head', 'tail', 'less', 'wc', 'jq', 'awk'])

// 列表命令（可折叠）
const BASH_LIST_COMMANDS = new Set(['ls', 'tree', 'du'])

// 静默命令（成功无输出）
const BASH_SILENT_COMMANDS = new Set(['mv', 'cp', 'rm', 'mkdir', 'chmod', 'touch'])
```

---

## 2. FileReadTool - 文件读取工具

### 工具角色

FileReadTool 就像**一个万能放大镜**——可以读取各种格式的文件，包括文本、图片、PDF 和 Jupyter Notebook。

### 输入 Schema

```typescript
z.strictObject({
  file_path: z.string().describe('文件的绝对路径'),
  offset: z.number().int().nonnegative().optional().describe('起始行号'),
  limit: z.number().int().positive().optional().describe('读取行数'),
  pages: z.string().optional().describe('PDF 页码范围（如 "1-5"）'),
})
```

### 输出类型（联合类型）

FileReadTool 支持 5 种输出类型，使用判别联合模式：

```typescript
type Output =
  | { type: 'text'; file: { filePath, content, numLines, startLine, totalLines } }
  | { type: 'image'; file: { base64, type, originalSize, dimensions } }
  | { type: 'notebook'; file: { filePath, cells } }
  | { type: 'pdf'; file: { filePath, base64, originalSize } }
  | { type: 'parts'; file: { filePath, count, outputDir } }  // PDF 页提取
  | { type: 'file_unchanged'; file: { filePath } }           // 未变更存根
```

### 文件类型处理流程

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      FileReadTool 文件类型处理                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│                    ┌──────────────────────┐                                 │
│                    │   读取文件扩展名      │                                 │
│                    └──────────────────────┘                                 │
│                              │                                               │
│          ┌───────────────────┼───────────────────┐                         │
│          │                   │                   │                          │
│          ▼                   ▼                   ▼                          │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                    │
│   │   .ipynb    │    │ 图片格式     │    │ PDF 格式    │                    │
│   │  Notebook   │    │ png/jpg/gif │    │   .pdf      │                    │
│   └──────┬──────┘    └──────┬──────┘    └──────┬──────┘                    │
│          │                   │                   │                          │
│          ▼                   ▼                   ▼                          │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────────┐                │
│   │readNotebook │    │readImageWith│    │ 有 pages 参数？  │                │
│   │   解析 cells │    │TokenBudget │    │                 │                │
│   │   返回 JSON  │    │ 自动压缩    │    │ Yes ──► extract │                │
│   └─────────────┘    └─────────────┘    │        PDFPages  │                │
│                                         │                 │                │
│                                         │ No ──► readPDF  │                │
│                                         └─────────────────┘                │
│                                                                              │
│                              │                                               │
│                              ▼                                               │
│                       ┌─────────────┐                                       │
│                       │  其他格式    │                                       │
│                       │  文本文件    │                                       │
│                       └──────┬──────┘                                       │
│                              │                                               │
│                              ▼                                               │
│                       ┌─────────────┐                                       │
│                       │readFileInRange│                                      │
│                       │ 行号格式输出  │                                       │
│                       │ 支持分页      │                                       │
│                       └─────────────┘                                       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 去重系统（节省 Token）

```typescript
// 文件未变更检测 - 返回存根而不是重新读取
if (existingState && !existingState.isPartialView) {
  const rangeMatch = existingState.offset === offset && existingState.limit === limit;
  if (rangeMatch && mtimeMs === existingState.timestamp) {
    // 文件内容和范围完全匹配，返回存根
    return { data: { type: 'file_unchanged', file: { filePath } } };
  }
}
```

### Token 预算控制

| 资源 | 限制 | 说明 |
|------|------|------|
| 文本文件 | 25K tokens | 超出时需要使用 offset/limit |
| 图片 | 动态压缩 | 根据 token 预算自动调整质量 |
| PDF | 最大 20 页/次 | 使用 pages 参数分批读取 |
| Notebook | 大小限制 | 超出时建议使用 jq 过滤 |

---

## 3. FileEditTool - 文件编辑工具

### 工具角色

FileEditTool 就像**一把精密刻刀**——用于精确替换文件中的文本片段，支持单次替换和全局替换。

### 输入 Schema

```typescript
z.strictObject({
  file_path: z.string().describe('要修改的文件绝对路径'),
  old_string: z.string().describe('要替换的文本'),
  new_string: z.string().describe('替换后的文本'),
  replace_all: z.boolean().default(false).describe('替换所有匹配项'),
})
```

### 安全机制

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      FileEditTool 安全机制                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 1. 写入权限检查                                                        │  │
│  │    checkWritePermissionForTool()                                       │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 2. 先读后写要求                                                        │  │
│  │    文件必须在 readFileState 中（之前已读取）                           │  │
│  │    → 防止"盲编辑"带来的意外损坏                                        │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 3. 陈旧性检测                                                          │  │
│  │    比较 mtime 与上次读取时间戳                                         │  │
│  │    → 检测文件是否被外部程序修改                                        │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 4. Team Memory 秘密保护                                                │  │
│  │    checkTeamMemSecrets()                                               │  │
│  │    → 阻止向团队记忆中注入凭证                                          │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 5. 引号标准化                                                          │  │
│  │    findActualString()                                                  │  │
│  │    → 处理弯引号 "" 和直引号 "" 的匹配                                  │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 引号标准化（处理 LLM 输出问题）

```typescript
// utils.ts - 处理弯引号标准化
export function findActualString(fileContent: string, searchString: string): string | null {
  // 1. 精确匹配
  if (fileContent.includes(searchString)) return searchString;

  // 2. 标准化后匹配（处理弯引号 "" → "" 等）
  const normalizedSearch = normalizeQuotes(searchString);
  const normalizedFile = normalizeQuotes(fileContent);

  // 3. 返回文件中的实际字符串（保持原始引号风格）
  if (normalizedFile.includes(normalizedSearch)) {
    // 找到并返回文件中实际的字符串
  }
}
```

### 执行流程

```typescript
async call(input, context, ...) {
  // 1. 预编辑备份（支持撤销）
  fileHistoryTrackEdit(fullFilePath, currentContent, input.old_string)

  // 2. 原子读取-修改-写入
  // 最小化 staleness 检查和写入之间的异步时间

  // 3. LSP 通知
  getLspServerManager().didChange(fullFilePath)
  getLspServerManager().didSave(fullFilePath)

  // 4. VSCode 通知（显示 diff）
  notifyVscodeFileUpdated(fullFilePath)

  // 5. 更新 readFileState
  readFileState.set(fullFilePath, { content: newContent, timestamp: Date.now() })
}
```

---

## 4. GlobTool - 文件模式匹配工具

### 工具角色

GlobTool 就像**一个文件探测器**——根据文件名模式快速定位文件，支持 glob 通配符语法。

### 输入 Schema

```typescript
z.strictObject({
  pattern: z.string().describe('Glob 模式（如 "**/*.ts"）'),
  path: z.string().optional().describe('搜索目录（默认当前目录）'),
})
```

### 输出 Schema

```typescript
z.object({
  durationMs: z.number().describe('执行时间（毫秒）'),
  numFiles: z.number().describe('匹配文件数量'),
  filenames: z.array(z.string()).describe('匹配的文件路径'),
  truncated: z.boolean().describe('结果是否被截断'),
})
```

### 执行特性

| 特性 | 说明 |
|------|------|
| **搜索引擎** | 使用 `fast-glob` 或 Bun 内置 `bfs` |
| **排序方式** | 按修改时间排序（最近修改在前） |
| **结果限制** | 默认 100 个文件 |
| **路径简化** | 相对于 CWD 的相对路径（节省 token） |

### 使用示例

```
模式: "**/*.ts"
输出: [
  "src/main.ts",
  "src/utils/helpers.ts",
  "src/components/Button.ts",
  ...
]
(Found 47 files in 23ms)
```

---

## 5. GrepTool - 内容搜索工具

### 工具角色

GrepTool 就像**一个内容扫描仪**——在文件内容中搜索正则表达式模式，基于 ripgrep 实现高速搜索。

### 输入 Schema

```typescript
z.strictObject({
  pattern: z.string().describe('正则表达式模式'),
  path: z.string().optional().describe('搜索路径（默认当前目录）'),
  glob: z.string().optional().describe('文件过滤模式（如 "*.ts"）'),
  output_mode: z.enum(['content', 'files_with_matches', 'count']).optional(),
  '-B': z.number().optional().describe('匹配前显示的行数'),
  '-A': z.number().optional().describe('匹配后显示的行数'),
  '-C': z.number().optional().describe('上下文行数'),
  '-n': z.boolean().optional().describe('显示行号'),
  '-i': z.boolean().optional().describe('忽略大小写'),
  type: z.string().optional().describe('文件类型（js, py, rust 等）'),
  head_limit: z.number().optional().describe('限制结果数量'),
  offset: z.number().optional().describe('跳过前 N 个结果'),
  multiline: z.boolean().optional().describe('多行模式'),
})
```

### 输出模式对比

| 模式 | 说明 | 等效 ripgrep 参数 |
|------|------|-------------------|
| `files_with_matches` | 仅返回匹配的文件路径（默认） | `-l` |
| `content` | 返回匹配的行及上下文 | 默认 |
| `count` | 返回每个文件的匹配计数 | `-c` |

### 自动排除目录

```typescript
// 版本控制系统目录（自动排除，减少噪音）
const VCS_DIRECTORIES_TO_EXCLUDE = [
  '.git', '.svn', '.hg', '.bzr', '.jj', '.sl'
]
```

### 默认限制

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `head_limit` | 250 | 防止上下文膨胀 |
| 列宽限制 | 500 字符 | 截断过长行 |
| `head_limit=0` | 无限制 | 显式请求无限制 |

---

## 工具对比总览

### 功能维度对比

| 维度 | BashTool | FileReadTool | FileEditTool | GlobTool | GrepTool |
|------|----------|--------------|--------------|----------|----------|
| **沙箱隔离** | ✅ 完整沙箱 | N/A | N/A | N/A | N/A |
| **后台执行** | ✅ 支持 | ❌ | ❌ | ❌ | ❌ |
| **Token 限制** | 输出截断 | 25K tokens | N/A | 100 文件 | 250 结果 |
| **权限模式** | 多层检查 | 只读 | 先读后写+写权限 | 只读 | 只读 |
| **输出格式** | 文本/图片 | 文本/图片/PDF/Notebook | patch diff | 文件列表 | 内容/文件/计数 |
| **分页支持** | 持久化输出 | offset/limit | N/A | truncated 标志 | head_limit/offset |

### 设计模式对比

| 模式 | 应用工具 | 说明 |
|------|----------|------|
| **Lazy Schema** | 所有工具 | `lazySchema()` 延迟 Zod schema 构造 |
| **Permission Matcher** | 所有工具 | `preparePermissionMatcher()` 支持 hook 白名单 |
| **Result Persistence** | BashTool | 大输出持久化到 `tool-results` 目录 |
| **Semantic Types** | BashTool, GrepTool | `semanticNumber()`/`semanticBoolean()` 预处理输入 |
| **Feature Flags** | BashTool | Bun `feature()` 编译时死代码消除 |

---

## 关键代码解读

### 1. BashTool 命令分类检测

```typescript
// src/tools/BashTool/BashTool.tsx:95-172

/**
 * 检测 Bash 命令是否为搜索/读取操作
 * 用于 UI 折叠显示
 *
 * 对于管道命令，所有部分都必须是搜索/读取命令
 * 才会将整个命令视为可折叠
 */
export function isSearchOrReadBashCommand(command: string): {
  isSearch: boolean;
  isRead: boolean;
  isList: boolean;
} {
  // 解析命令（处理管道和操作符）
  const partsWithOperators = splitCommandWithOperators(command);

  let hasSearch = false;
  let hasRead = false;
  let hasList = false;

  for (const part of partsWithOperators) {
    // 跳过重定向目标
    if (skipNextAsRedirectTarget) continue;

    // 跳过操作符（|, &&, ||, ;）
    if (part === '||' || part === '&&' || part === '|') continue;

    // 跳过语义中立命令（echo, printf, true）
    if (BASH_SEMANTIC_NEUTRAL_COMMANDS.has(baseCommand)) continue;

    // 检查是否为搜索/读取/列表命令
    const isPartSearch = BASH_SEARCH_COMMANDS.has(baseCommand);
    const isPartRead = BASH_READ_COMMANDS.has(baseCommand);
    const isPartList = BASH_LIST_COMMANDS.has(baseCommand);

    // 如果都不是，则整个命令不可折叠
    if (!isPartSearch && !isPartRead && !isPartList) {
      return { isSearch: false, isRead: false, isList: false };
    }

    // 累计类型
    if (isPartSearch) hasSearch = true;
    if (isPartRead) hasRead = true;
    if (isPartList) hasList = true;
  }

  return { isSearch: hasSearch, isRead: hasRead, isList: hasList };
}
```

### 2. GlobTool 核心实现

```typescript
// src/tools/GlobTool/GlobTool.ts:154-198

export const GlobTool = buildTool({
  name: GLOB_TOOL_NAME,
  searchHint: 'find files by name pattern or wildcard',
  maxResultSizeChars: 100_000,

  isConcurrencySafe() { return true },  // 只读，并发安全
  isReadOnly() { return true },          // 纯读取操作

  async call(input, { abortController, getAppState, globLimits }) {
    const start = Date.now();
    const appState = getAppState();
    const limit = globLimits?.maxResults ?? 100;  // 默认 100 文件

    // 调用底层 glob 函数（fast-glob 或 bfs）
    const { files, truncated } = await glob(
      input.pattern,
      GlobTool.getPath(input),  // 解析路径
      { limit, offset: 0 },
      abortController.signal,
      appState.toolPermissionContext,
    );

    // 转换为相对路径（节省 token）
    const filenames = files.map(toRelativePath);

    return {
      data: {
        filenames,
        durationMs: Date.now() - start,
        numFiles: filenames.length,
        truncated,
      },
    };
  },

  mapToolResultToToolResultBlockParam(output, toolUseID) {
    if (output.filenames.length === 0) {
      return { tool_use_id: toolUseID, type: 'tool_result', content: 'No files found' };
    }

    return {
      tool_use_id: toolUseID,
      type: 'tool_result',
      content: [
        ...output.filenames,
        ...(output.truncated
          ? ['(Results are truncated. Consider using a more specific path or pattern.)']
          : []),
      ].join('\n'),
    };
  },
});
```

### 3. GrepTool head_limit 实现

```typescript
// src/tools/GrepTool/GrepTool.ts:110-128

const DEFAULT_HEAD_LIMIT = 250;  // 默认限制

function applyHeadLimit<T>(
  items: T[],
  limit: number | undefined,
  offset: number = 0,
): { items: T[]; appliedLimit: number | undefined } {
  // 显式传 0 = 无限制逃生舱
  if (limit === 0) {
    return { items: items.slice(offset), appliedLimit: undefined };
  }

  const effectiveLimit = limit ?? DEFAULT_HEAD_LIMIT;
  const sliced = items.slice(offset, offset + effectiveLimit);

  // 只有实际截断时才报告 appliedLimit
  // 这样模型知道可能还有更多结果，可以用 offset 分页
  const wasTruncated = items.length - offset > effectiveLimit;

  return {
    items: sliced,
    appliedLimit: wasTruncated ? effectiveLimit : undefined,
  };
}
```

---

## 设计亮点

### 1. 统一的工具架构

所有工具都遵循相同的模式：

```
buildTool({
  name,              // 身份标识
  inputSchema,       // Zod 输入验证
  outputSchema,      // Zod 输出类型
  call(),            // 核心执行逻辑
  checkPermissions(),// 权限检查
  validateInput(),   // 输入验证
  isConcurrencySafe(), // 并发安全性
  isReadOnly(),      // 只读性
  renderToolUseMessage(), // UI 渲染
})
```

### 2. 权限分层设计

```
┌─────────────────────────────────────────────────────────────┐
│                      权限分层金字塔                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Level 5: 用户确认                                           │
│  ↑        (canUseTool 弹窗)                                  │
│  │                                                           │
│  Level 4: Hook 检查                                          │
│  │        (PreToolUse hooks)                                 │
│  │                                                           │
│  Level 3: 工具级权限                                         │
│  │        (checkPermissions)                                 │
│  │                                                           │
│  Level 2: 输入验证                                           │
│  │        (validateInput)                                    │
│  │                                                           │
│  Level 1: Schema 验证                                        │
│           (Zod safeParse)                                    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 3. Token 预算控制

| 工具 | 控制策略 | 目的 |
|------|----------|------|
| FileReadTool | 25K token 上限 | 防止大文件占满上下文 |
| GlobTool | 100 文件限制 | 防止目录遍历结果膨胀 |
| GrepTool | 250 结果限制 | 防止搜索结果膨胀 |
| BashTool | 30KB 持久化 | 大输出写入磁盘 |

### 4. 智能去重

```typescript
// FileReadTool: 相同文件重复读取返回存根
if (existingState && mtimeMatch && rangeMatch) {
  return { data: { type: 'file_unchanged' } };
}

// FileEditTool: 相同内容拒绝编辑
if (old_string === new_string) {
  return { result: false, message: 'No changes to make' };
}
```

---

## 文件路径索引

### BashTool 相关文件

| 文件 | 职责 |
|------|------|
| `src/tools/BashTool/BashTool.tsx` | 主实现（UI + 执行逻辑） |
| `src/tools/BashTool/bashPermissions.ts` | 权限规则 |
| `src/tools/BashTool/shouldUseSandbox.ts` | 沙箱决策逻辑 |
| `src/tools/BashTool/modeValidation.ts` | 模式权限验证 |
| `src/tools/BashTool/readOnlyValidation.ts` | 只读命令检测 |
| `src/tools/BashTool/commandSemantics.ts` | 命令语义分析 |

### FileReadTool 相关文件

| 文件 | 职责 |
|------|------|
| `src/tools/FileReadTool/FileReadTool.ts` | 主实现 |
| `src/tools/FileReadTool/limits.ts` | Token/大小限制配置 |
| `src/tools/FileReadTool/UI.ts` | UI 渲染组件 |
| `src/tools/FileReadTool/prompt.ts` | 工具描述 |

### FileEditTool 相关文件

| 文件 | 职责 |
|------|------|
| `src/tools/FileEditTool/FileEditTool.ts` | 主实现 |
| `src/tools/FileEditTool/utils.ts` | 引号标准化、patch 生成 |
| `src/tools/FileEditTool/constants.ts` | 常量定义 |

### GlobTool 相关文件

| 文件 | 职责 |
|------|------|
| `src/tools/GlobTool/GlobTool.ts` | 主实现 |
| `src/tools/GlobTool/prompt.ts` | 工具描述 |
| `src/tools/GlobTool/UI.ts` | UI 渲染 |
| `src/utils/glob.ts` | 底层 glob 实现 |

### GrepTool 相关文件

| 文件 | 职责 |
|------|------|
| `src/tools/GrepTool/GrepTool.ts` | 主实现 |
| `src/tools/GrepTool/prompt.ts` | 工具描述 |
| `src/tools/GrepTool/UI.ts` | UI 渲染 |
| `src/utils/ripgrep.ts` | ripgrep 包装器 |

---

## 总结

Claude Code 的五大核心工具展示了统一的架构设计：

1. **一致的接口**：所有工具都使用 `buildTool` 工厂函数，确保默认值一致性
2. **多层安全**：从 Schema 验证到用户确认，层层把关
3. **Token 优化**：通过限制、去重、分页等机制控制上下文大小
4. **类型安全**：Zod schema 确保输入输出的类型正确性
5. **UI 一致性**：统一的渲染接口，支持折叠、错误显示等