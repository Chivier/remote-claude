# 类型定义 (types.ts)

`types.ts` 定义了 Daemon 中所有共享的 TypeScript 类型，包括 RPC 协议、会话状态、流事件和 Claude CLI 输出格式。

**源文件**：`daemon/src/types.ts`

## RPC 协议类型

### RpcRequest

```typescript
interface RpcRequest {
    method: string;                      // RPC 方法名
    params?: Record<string, unknown>;    // 方法参数
    id?: string;                         // 请求 ID（可选）
}
```

### RpcResponse

```typescript
interface RpcResponse {
    result?: unknown;                    // 成功时的结果
    error?: {
        code: number;                    // 错误码
        message: string;                 // 错误消息
        data?: unknown;                  // 附加错误数据
    };
    id?: string;                         // 对应请求的 ID
}
```

## 会话类型

### SessionStatus

```typescript
type SessionStatus = "idle" | "busy" | "error" | "destroyed";
```

| 状态 | 说明 |
|------|------|
| `idle` | 空闲，没有 Claude 进程在运行 |
| `busy` | 正在处理消息，Claude 进程运行中 |
| `error` | 出错状态 |
| `destroyed` | 已销毁 |

### PermissionMode

```typescript
type PermissionMode = "auto" | "code" | "plan" | "ask";
```

### modeToCliFlag(mode) -> string[]

将权限模式转换为 Claude CLI 的命令行标志。

```typescript
function modeToCliFlag(mode: PermissionMode): string[] {
    switch (mode) {
        case "auto":
            return ["--dangerously-skip-permissions"];
        case "code":
            return [];  // SDK 级别，CLI 无直接标志
        case "plan":
            return [];  // SDK 级别
        case "ask":
            return [];  // 默认行为
        default:
            return ["--dangerously-skip-permissions"];
    }
}
```

> **注意**：只有 `auto` 模式有对应的 CLI 标志。`code`、`plan`、`ask` 是 SDK 级别的概念，在 `--print` 模式下 CLI 不直接支持。默认行为（不带标志）等同于 `ask` 模式。

### ManagedSession

会话的核心数据结构。

```typescript
interface ManagedSession {
    sessionId: string;              // 会话唯一 ID (UUID)
    path: string;                   // 项目路径
    mode: PermissionMode;           // 权限模式
    status: SessionStatus;          // 当前状态
    sdkSessionId: string | null;    // Claude SDK 会话 ID（用于 --resume）
    createdAt: Date;                // 创建时间
    lastActivityAt: Date;           // 最后活动时间
}
```

### SessionInfo

用于 API 返回的会话信息（Date 序列化为 ISO 字符串）。

```typescript
interface SessionInfo {
    sessionId: string;
    path: string;
    status: SessionStatus;
    mode: PermissionMode;
    sdkSessionId: string | null;
    model: string | null;           // 模型名称（如 claude-sonnet-4-20250514）
    createdAt: string;              // ISO 时间字符串
    lastActivityAt: string;
}
```

## 流事件类型

### StreamEventType

```typescript
type StreamEventType =
    | "text"         // 完整文本块
    | "tool_use"     // 工具调用
    | "tool_result"  // 工具结果
    | "result"       // 完成事件
    | "queued"       // 消息已排队
    | "error"        // 错误
    | "system"       // 系统事件
    | "partial"      // 流式文本增量
    | "ping"         // 心跳
    | "interrupted"; // 操作被中断
```

### StreamEvent

```typescript
interface StreamEvent {
    type: StreamEventType;
    content?: string;          // text/partial 的文本内容
    tool?: string;             // tool_use 的工具名
    input?: unknown;           // tool_use 的输入参数
    output?: unknown;          // tool_result 的输出
    session_id?: string;       // result 事件的 SDK Session ID
    position?: number;         // queued 事件的队列位置
    message?: string;          // error 事件的错误消息 / tool_use 的描述
    subtype?: string;          // system 事件的子类型
    model?: string;            // system.init 的模型名称
    raw?: unknown;             // Claude CLI 原始数据
}
```

## 消息队列类型

### QueuedUserMessage

```typescript
interface QueuedUserMessage {
    message: string;     // 用户消息内容
    timestamp: number;   // 入队时间戳
}
```

### QueuedResponse

```typescript
interface QueuedResponse {
    event: StreamEvent;  // 响应事件
    timestamp: number;   // 缓冲时间戳
}
```

## RPC 方法参数和结果类型

### CreateSessionParams / CreateSessionResult

```typescript
interface CreateSessionParams {
    path: string;              // 项目路径（必需）
    mode?: PermissionMode;     // 权限模式（可选，默认 auto）
}

interface CreateSessionResult {
    sessionId: string;         // 新创建的会话 ID
}
```

### SendMessageParams

```typescript
interface SendMessageParams {
    sessionId: string;         // 会话 ID
    message: string;           // 用户消息
}
```

> 注意：`session.send` 没有 Result 类型，因为它返回 SSE 流。

### ResumeSessionParams / ResumeSessionResult

```typescript
interface ResumeSessionParams {
    sessionId: string;             // 会话 ID
    sdkSessionId?: string;         // SDK Session ID（可选）
}

interface ResumeSessionResult {
    ok: boolean;
    fallback?: boolean;            // 是否降级为注入历史
    newSdkSessionId?: string;      // 新的 SDK Session ID
}
```

### DestroySessionParams

```typescript
interface DestroySessionParams {
    sessionId: string;
}
```

### SetModeParams

```typescript
interface SetModeParams {
    sessionId: string;
    mode: PermissionMode;
}
```

### InterruptSessionParams

```typescript
interface InterruptSessionParams {
    sessionId: string;
}
```

### HealthCheckResult

```typescript
interface HealthCheckResult {
    ok: boolean;
    sessions: number;
    sessionsByStatus: Record<string, number>;
    uptime: number;                // 秒
    memory: {
        rss: number;               // MB
        heapUsed: number;          // MB
        heapTotal: number;         // MB
    };
    nodeVersion: string;
    pid: number;
}
```

### MonitorSessionDetail / MonitorSessionsResult

```typescript
interface MonitorSessionDetail {
    sessionId: string;
    path: string;
    status: SessionStatus;
    mode: PermissionMode;
    model: string | null;
    sdkSessionId: string | null;
    createdAt: string;
    lastActivityAt: string;
    queue: {
        userPending: number;
        responsePending: number;
        clientConnected: boolean;
    };
}

interface MonitorSessionsResult {
    sessions: MonitorSessionDetail[];
    totalSessions: number;
    uptime: number;
}
```

## Claude CLI JSON-lines 协议

### ClaudeStdoutMessage

Claude CLI 在 `--output-format stream-json` 模式下输出的 JSON 行格式。

```typescript
interface ClaudeStdoutMessage {
    type: string;                  // system | assistant | stream_event | tool_progress | result
    subtype?: string;              // init (for system)
    session_id?: string;

    // assistant 消息
    message?: {
        role: string;
        content: Array<{
            type: string;          // text | tool_use
            text?: string;         // text 类型的内容
            name?: string;         // tool_use 的工具名
            input?: unknown;       // tool_use 的输入
            id?: string;           // tool_use 的 ID
        }>;
    };

    // stream_event
    event?: {
        type: string;              // content_block_delta | content_block_start
        index?: number;
        delta?: {
            type?: string;
            text?: string;         // 文本增量
            partial_json?: string; // JSON 增量
        };
        content_block?: {
            type: string;          // text | tool_use
            text?: string;
            name?: string;
            id?: string;
        };
    };

    // result
    duration_ms?: number;
    usage?: {
        input_tokens: number;
        output_tokens: number;
    };

    // tool_progress
    tool_name?: string;
    status?: string;
}
```

> **注意**：系统使用 `--print` 模式（每消息生成进程），因此不存在 stdin 输入类型。消息通过 CLI 参数传递。
