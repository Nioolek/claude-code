# Claude Code Bridge 系统深度分析报告

## 1. 模块概述

Bridge 系统实现 Claude Code 的 Remote Control 功能，支持本地 CLI 会话与远程客户端（claude.ai、IDE 扩展）的双向通信。用户可以通过 Web 界面控制 CLI 会话、发送消息、接收权限提示。

### 1.2 文件结构

```
src/bridge/
├── types.ts                    # 核心类型定义
├── bridgeApi.ts                # API 客户端（Environments层）
├── bridgeMessaging.ts          # 消息解析/路由
├── jwtUtils.ts                 # JWT Token 刷新调度器
├── bridgeMain.ts               # 独立 bridge 循环
├── replBridge.ts               # REPL嵌入式 bridge
├── remoteBridgeCore.ts         # V2 env-less bridge 核心
├── replBridgeTransport.ts      # Transport 抽象层
├── sessionRunner.ts            # 子进程 spawning
├── bridgeUI.ts                 # 终端 UI（QR码、状态）
├── trustedDevice.ts            # 设备 Token 注册
├── workSecret.ts               # Work Secret 解码
├── sessionIdCompat.ts          # Session ID 格式转换
├── bridgePointer.ts            # 崩溃恢复指针
└── inboundAttachments.ts       # 文件附件解析
```

## 2. 核心组件分析

### 2.1 Type System (`types.ts`)

**BridgeConfig 类型**:

```typescript
type BridgeConfig = {
  dir: string
  machineName: string
  branch: string
  gitRepoUrl: string | null
  maxSessions: number
  spawnMode: 'single-session' | 'worktree' | 'same-dir'
  bridgeId: string              // Client-generated UUID
  workerType: string            // 'claude_code' | 'claude_code_assistant'
  environmentId: string
  apiBaseUrl: string
  sessionIngressUrl: string
}
```

**WorkSecret 解码结构**:

```typescript
type WorkSecret = {
  version: number
  session_ingress_token: string  // JWT
  api_base_url: string
  sources: Array<{...}>
  auth: Array<{type: string; token: string}>
}
```

### 2.2 API Client (`bridgeApi.ts`)

**Endpoints**:

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST /v1/environments/bridge` | `registerBridgeEnvironment` | 注册 bridge 环境 |
| `GET /v1/environments/{id}/work/poll` | `pollForWork` | Long-poll 获取 work |
| `POST /v1/environments/{id}/work/{id}/ack` | `acknowledgeWork` | 确认 work 收到 |
| `POST /v1/environments/{id}/work/{id}/heartbeat` | `heartbeatWork` | 延长 work lease |
| `DELETE /v1/environments/bridge/{id}` | `deregisterEnvironment` | 关闭时清理 |

**OAuth Retry Pattern**:

```typescript
async function withOAuthRetry<T>(fn, context): Promise<{status, data}> {
  const response = await fn(accessToken)
  if (response.status !== 401) return response

  const refreshed = await deps.onAuth401(accessToken)
  if (refreshed) return fn(resolveAuth())  // Retry with new token
  return response
}
```

### 2.3 JWT Token Management (`jwtUtils.ts`)

**Token Refresh Scheduler**:

```typescript
function createTokenRefreshScheduler({
  getAccessToken,
  onRefresh,
  refreshBufferMs = 5 * 60 * 1000  // 5 minutes before expiry
}): {
  schedule(sessionId, token)
  scheduleFromExpiresIn(sessionId, expiresInSeconds)
  cancel(sessionId)
}
```

**Key Features**:
- 解码 JWT `exp` claim（无签名验证）
- 在过期前 5 分钟调度刷新
- Generation counter 防止过期异步操作
- 最大 3 次连续失败后放弃

### 2.4 Transport Layer (`replBridgeTransport.ts`)

**V1 Adapter (HybridTransport)**:

```typescript
function createV1ReplTransport(hybrid: HybridTransport): ReplBridgeTransport {
  return {
    write: msg => hybrid.write(msg),
    writeBatch: msgs => hybrid.writeBatch(msgs),
    close: () => hybrid.close(),
    getLastSequenceNum: () => 0,  // v1 无 SSE sequence numbers
  }
}
```

**V2 Adapter (SSETransport + CCRClient)**:

```typescript
async function createV2ReplTransport({
  sessionUrl,
  ingressToken,
  sessionId,
  epoch,
  initialSequenceNum,
  getAuthToken,
}): Promise<ReplBridgeTransport>
```

**V2 Features**:
- SSE for reads (`/worker/events/stream`)
- CCRClient for writes (`POST /worker/events`)
- Heartbeat with epoch validation

### 2.5 Message Protocol (`bridgeMessaging.ts`)

**Message Types**:

```typescript
type SDKMessage =
  | { type: 'user'; message: {...}; uuid?: string }
  | { type: 'assistant'; message: {...}; uuid?: string }
  | { type: 'result'; subtype: 'success' | 'error'; ... }

type SDKControlRequest = {
  type: 'control_request'
  request_id: string
  request: {
    subtype: 'initialize' | 'set_model' | 'interrupt' |
             'set_permission_mode' | 'can_use_tool'
  }
}
```

**Echo Deduplication**:

```typescript
class BoundedUUIDSet {
  private readonly ring: (string | undefined)[]
  private readonly set = new Set<string>()
  private writeIdx = 0

  add(uuid: string): void {
    if (this.set.has(uuid)) return
    // Ring buffer for bounded memory
  }
}
```

### 2.6 Session Runner (`sessionRunner.ts`)

**Child Process Spawning**:

```typescript
function createSessionSpawner(deps): SessionSpawner {
  return {
    spawn(opts: SessionSpawnOpts, dir: string): SessionHandle {
      const child = spawn(execPath, [
        '--print',
        '--sdk-url', opts.sdkUrl,
        '--session-id', opts.sessionId,
        '--input-format', 'stream-json',
        '--output-format', 'stream-json',
      ], {
        cwd: dir,
        stdio: ['pipe', 'pipe', 'pipe'],
        env: {
          CLAUDE_CODE_SESSION_ACCESS_TOKEN: opts.accessToken,
          CLAUDE_CODE_USE_CCR_V2: opts.useCcrV2 ? '1' : undefined,
        }
      })

      return {
        sessionId,
        done: Promise<SessionDoneStatus>,
        kill(), forceKill(),
        writeStdin(data),
        updateAccessToken(token),
      }
    }
  }
}
```

## 3. Session ID Compatibility

**Tag Translation**:

```typescript
// cse_* (infra) <-> session_* (compat layer)
function toCompatSessionId(id: string): string {
  if (!id.startsWith('cse_')) return id
  return 'session_' + id.slice('cse_'.length)
}

function toInfraSessionId(id: string): string {
  if (!id.startsWith('session_')) return id
  return 'cse_' + id.slice('session_'.length)
}
```

## 4. Trusted Device Authentication

**Enrollment Flow**:

```typescript
async function enrollTrustedDevice(): Promise<void> {
  // 1. Check GrowthBook gate
  if (!(await checkGate_CACHED_OR_BLOCKING(TRUSTED_DEVICE_GATE))) return

  // 2. POST /api/auth/trusted_devices
  const response = await axios.post(
    `${baseUrl}/api/auth/trusted_devices`,
    { display_name: `Claude Code on ${hostname()}` }
  )

  // 3. Persist to keychain
  storageData.trustedDeviceToken = response.data.device_token
}
```

## 5. State Synchronization Flows

### 5.1 V1 (Env-based) Flow

```
1. POST /v1/environments/bridge → environment_id
2. GET /v1/environments/{id}/work/poll (long-poll)
3. Receive WorkResponse with secret (JWT)
4. POST /v1/environments/{id}/work/{id}/ack
5. Build WebSocket URL from api_base_url
6. Connect HybridTransport (WS read + POST write)
7. Spawn child process with SDK URL + JWT
8. Relay messages: child stdout → WS, WS → child stdin
9. Heartbeat: POST /v1/environments/{id}/work/{id}/heartbeat
```

### 5.2 V2 (Env-less) Flow

```
1. POST /v1/code/sessions → session.id (cse_*)
2. POST /v1/code/sessions/{id}/bridge → worker_jwt, epoch
3. Create SSETransport + CCRClient
4. SSE stream: GET /v1/code/sessions/{id}/worker/events/stream
5. Writes: POST /v1/code/sessions/{id}/worker/events
6. Heartbeat via CCRClient (includes epoch)
7. Token refresh: Re-call /bridge → new JWT + epoch
```

## 6. Security Considerations

### 6.1 Authentication Layers

| Layer | Purpose | Token Type |
|-------|---------|------------|
| OAuth | User authentication | Access Token (~4h TTL) |
| Session Ingress JWT | Session-level auth | JWT (~5h TTL) |
| Trusted Device | Elevated security tier | Device Token (90d TTL) |

### 6.2 Path Validation

```typescript
const SAFE_ID_PATTERN = /^[a-zA-Z0-9_-]+$/

function validateBridgeId(id: string, label: string): string {
  if (!id || !SAFE_ID_PATTERN.test(id)) {
    throw new Error(`Invalid ${label}: contains unsafe characters`)
  }
  return id
}
```

## 7. Design Highlights

### 7.1 Dependency Injection
- Heavy dependencies are injected to avoid bundle bloat
- `toSDKMessages`, `onAuth401`, `getPollIntervalConfig` injected

### 7.2 Flush Gate Pattern

```typescript
class FlushGate<T> {
  start()    // Begin queueing
  enqueue(...items)  // Queue or return false
  end()      // End gating, return queued items
  drop()     // End gating, discard queue
}
```

### 7.3 Capacity Wake

```typescript
function createCapacityWake(signal: AbortSignal): CapacitySignal {
  // Allows at-capacity sleep to be interrupted
  return { sleep(ms), wake() }
}
```

## 8. Feature Flags

| Flag | Purpose |
|------|---------|
| `BRIDGE_MODE` | Build-time enable bridge |
| `tengu_ccr_bridge` | Runtime gate for Remote Control |
| `tengu_bridge_repl_v2` | Enable v2 env-less path |
| `tengu_ccr_bridge_multi_session` | Multi-session spawn modes |

## 9. File Path Index

| 文件 | Lines | Purpose |
|------|-------|---------|
| `src/bridge/types.ts` | 263 | Core type definitions |
| `src/bridge/bridgeApi.ts` | 540 | API client implementation |
| `src/bridge/jwtUtils.ts` | 257 | Token refresh scheduler |
| `src/bridge/bridgeMessaging.ts` | 462 | Message parsing/routing |
| `src/bridge/bridgeMain.ts` | ~3000 | Standalone bridge loop |
| `src/bridge/replBridge.ts` | ~2500 | REPL bridge core |
| `src/bridge/remoteBridgeCore.ts` | 1009 | V2 env-less bridge |
| `src/bridge/sessionRunner.ts` | 551 | Child process spawner |
| `src/bridge/trustedDevice.ts` | 211 | Device enrollment |