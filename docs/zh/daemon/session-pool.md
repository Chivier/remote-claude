# 会话池 (session-pool.ts)

`session-pool.ts` 是 Daemon 的核心模块，管理 Claude CLI 会话的生命周期，实现每消息生成进程的架构。

**源文件**：`daemon/src/session-pool.ts`

## 职责

1. 创建和管理 Claude 会话
2. 为每条消息生成 `claude --print` 子进程
3. 解析 Claude CLI 的 JSON-lines 输出并转换为 StreamEvent
4. 管理消息队列（Claude 忙时排队）
5. 维护会话的 SDK Session ID（用于 `--resume`）
6. 处理进程中断和清理

## 内部会话结构

```typescript
interface InternalSession extends ManagedSession {
    process: ChildProcess | null;   // 当前运行的 Claude 进程（仅处理消息时）
    queue: MessageQueue;            // 消息队列
    processing: boolean;            // 是否正在处理消息
    model: string | null;           // Claude 报告的模型名称
}
```

## SessionPool 类

### 会话创建

#### create(path, mode) -> sessionId

创建一个新会话。这是一个**轻量级操作**——不会启动任何 Claude CLI 进程，只是注册会话状态。

```typescript
async create(path: string, mode: PermissionMode = "auto"): Promise<string> {
    if (!existsSync(path)) {
        throw new Error(`Path does not exist: ${path}`);
    }
    const sessionId = uuidv4();
    // 初始化会话状态...
    return sessionId;
}
```

初始状态：`status = "idle"`，`process = null`，`processing = false`。

### 消息发送

#### `send(sessionId, message) -> AsyncGenerator<StreamEvent>`

发送消息到会话。如果 Claude 正在忙，消息会被排队。

```typescript
async *send(sessionId: string, message: string): AsyncGenerator<StreamEvent> {
    const session = this.getSession(sessionId);

    if (session.processing) {
        const position = session.queue.enqueueUser(message);
        yield { type: "queued", position };
        return;
    }

    yield* this.processMessage(session, message);
}
```

### 消息处理

#### `processMessage(session, message) -> AsyncGenerator<StreamEvent>`

核心方法：为单条消息生成 Claude CLI 进程并流式产出事件。

**CLI 命令构建**：

```bash
claude --print "<message>" \
       --output-format stream-json \
       --verbose \
       [--resume <sdkSessionId>] \
       [--dangerously-skip-permissions]
```

参数说明：
- `--print` — 单次处理模式，处理完自动退出
- `--output-format stream-json` — 输出 JSON-lines 格式
- `--verbose` — 输出详细的流式事件（包括 stream_event）
- `--resume` — 恢复之前的对话上下文
- `--dangerously-skip-permissions` — auto 模式下使用

**进程环境**：

```typescript
spawn("claude", args, {
    cwd: session.path,
    stdio: ["pipe", "pipe", "pipe"],
    env: { ...process.env, TERM: "dumb" },
});
```

`TERM: "dumb"` 防止 Claude CLI 输出 ANSI 控制字符。

**事件队列机制**：

使用内部事件队列和 Promise 实现异步事件产出：

```typescript
const eventQueue: StreamEvent[] = [];
let resolveWait: (() => void) | null = null;
let done = false;

const pushEvent = (event: StreamEvent) => {
    eventQueue.push(event);
    if (resolveWait) {
        resolveWait();
        resolveWait = null;
    }
};
```

主循环不断从队列取出事件并 yield，当队列为空且进程未结束时，使用 Promise 等待下一个事件：

```typescript
while (true) {
    if (eventQueue.length > 0) {
        const event = eventQueue.shift()!;
        yield event;
        if (event.type === "result" || event.type === "error" || event.type === "interrupted") {
            break;
        }
    } else if (done) {
        break;
    } else {
        await new Promise<void>((resolve) => { resolveWait = resolve; });
    }
}
```

**stdout 解析**：

使用 `readline.createInterface` 逐行读取 stdout，每行解析为 JSON：

```typescript
stdoutReader.on("line", (line) => {
    const parsed = JSON.parse(line);  // ClaudeStdoutMessage

    // 提取模型名称
    if (parsed.type === "system" && parsed.subtype === "init") {
        session.model = parsed.model;
    }

    // 转换为 StreamEvent
    const event = this.convertToStreamEvent(parsed);

    // 捕获 SDK Session ID
    if (event.session_id) {
        session.sdkSessionId = event.session_id;
    }

    pushEvent(event);
});
```

**进程退出处理**：

```typescript
child.on("exit", (code, signal) => {
    // exit code 0 是正常的（--print 模式处理完就退出）
    if (code !== 0 && code !== null) {
        pushEvent({
            type: "error",
            message: `Claude process exited abnormally (code=${code}, signal=${signal})`,
        });
    }
    done = true;
});
```

**清理**：

```typescript
finally {
    session.process = null;
    session.processing = false;
    session.status = "idle";

    // 终止残留进程
    if (child && !child.killed) {
        child.kill("SIGTERM");
        setTimeout(() => {
            if (!child.killed) child.kill("SIGKILL");
        }, 3000);
    }

    // 处理排队的下一条消息
    if (session.queue.hasUserPending() && session.status === "idle") {
        const next = session.queue.dequeueUser();
        if (next) {
            this.processQueuedMessage(session, next.message);
        }
    }
}
```

### 事件转换

#### convertToStreamEvent(msg: ClaudeStdoutMessage) -> StreamEvent

将 Claude CLI 的原始 JSON 输出转换为统一的 StreamEvent 格式。

| Claude CLI 类型 | StreamEvent 类型 | 说明 |
|----------------|-----------------|------|
| `system` | `system` | 系统消息（init 等），提取 model |
| `assistant` (text blocks) | `text` | 完整的文本响应 |
| `assistant` (tool blocks) | `tool_use` | 工具调用 |
| `stream_event` (content_block_delta, text) | `partial` | 流式文本增量 |
| `stream_event` (content_block_delta, partial_json) | `partial` | 流式 JSON 增量 |
| `stream_event` (content_block_start, tool_use) | `tool_use` | 工具调用开始 |
| `tool_progress` | `tool_use` | 工具执行进度 |
| `result` | `result` | 完成事件，包含 session_id |

### 其他方法

#### resume(sessionId, sdkSessionId)

恢复会话。在每消息生成模式下，只需更新 `sdkSessionId`，下次 `send()` 时会自动使用 `--resume`。

#### destroy(sessionId)

销毁会话：终止运行中的进程，清空队列，从 Map 中移除。

进程终止使用 SIGTERM，3 秒后如果未终止则发送 SIGKILL。

#### setMode(sessionId, mode)

更新权限模式。下次生成进程时会使用新模式。

#### interrupt(sessionId) -> boolean

中断当前操作。向 Claude CLI 进程发送 SIGTERM，清空消息队列。

返回 `true` 表示确实有操作被中断，`false` 表示会话空闲。

#### clientDisconnect(sessionId) / clientReconnect(sessionId)

管理客户端连接状态，用于消息队列的响应缓冲。

#### getQueueStats(sessionId)

返回消息队列统计：待处理用户消息数、缓冲响应数、客户端连接状态。

#### destroyAll()

销毁所有会话。在服务器关闭时调用。

## 与其他模块的关系

- **server.ts** — 调用所有公开方法
- **message-queue.ts** — 每个会话持有一个 MessageQueue 实例
- **types.ts** — 使用 StreamEvent、SessionStatus、PermissionMode 等类型
