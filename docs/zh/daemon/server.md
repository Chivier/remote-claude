# RPC 服务器 (server.ts)

`server.ts` 是 Daemon 的 HTTP 入口，基于 Express 框架实现 JSON-RPC 服务器。

**源文件**：`daemon/src/server.ts`

## 职责

1. 提供 JSON-RPC HTTP 端点 (`POST /rpc`)
2. 路由所有 RPC 方法到对应的处理函数
3. 处理 SSE 流式响应（`session.send`）
4. 管理 SSE 连接的心跳和断连检测
5. 提供健康检查和监控端点
6. 优雅关闭

## 服务器配置

```typescript
const PORT = parseInt(process.env.DAEMON_PORT || "9100", 10);
const HOST = "127.0.0.1";  // 仅绑定本地回环地址
```

端口通过环境变量 `DAEMON_PORT` 配置，默认 9100。绑定地址固定为 `127.0.0.1`，只能通过 SSH 隧道访问。

## 全局实例

```typescript
const sessionPool = new SessionPool();
const skillManager = new SkillManager();
const startTime = Date.now();  // 用于计算 uptime
```

## RPC 方法路由

所有请求发送到 `POST /rpc`，根据 `method` 字段路由：

| 方法 | 处理函数 | 响应类型 |
|------|----------|---------|
| `session.create` | `handleCreateSession` | JSON |
| `session.send` | `handleSendMessage` | SSE |
| `session.resume` | `handleResumeSession` | JSON |
| `session.destroy` | `handleDestroySession` | JSON |
| `session.list` | `handleListSessions` | JSON |
| `session.set_mode` | `handleSetMode` | JSON |
| `session.interrupt` | `handleInterruptSession` | JSON |
| `session.queue_stats` | `handleQueueStats` | JSON |
| `session.reconnect` | `handleReconnect` | JSON |
| `health.check` | `handleHealthCheck` | JSON |
| `monitor.sessions` | `handleMonitorSessions` | JSON |

## 方法处理

### handleCreateSession

1. 验证必需参数 `path`
2. 调用 `skillManager.syncToProject(path)` 同步技能文件
3. 调用 `sessionPool.create(path, mode)` 创建会话
4. 返回 `{ sessionId }`

### handleSendMessage（SSE 流式）

这是最复杂的处理函数，使用 SSE 进行流式响应：

```typescript
// 设置 SSE 响应头
res.setHeader("Content-Type", "text/event-stream");
res.setHeader("Cache-Control", "no-cache");
res.setHeader("Connection", "keep-alive");
res.setHeader("X-Accel-Buffering", "no");  // 禁用 nginx 缓冲
```

**客户端断连检测**：

```typescript
let clientDisconnected = false;
res.on("close", () => {
    clientDisconnected = true;
    sessionPool.clientDisconnect(params.sessionId);
});
```

当客户端断连时，后续的事件会通过 `sessionPool.bufferEvent()` 缓存，而非尝试写入已关闭的连接。

**心跳机制**：

```typescript
const keepaliveInterval = setInterval(() => {
    res.write(`data: ${JSON.stringify({ type: "ping" })}\n\n`);
}, 30000);  // 每 30 秒
```

防止 SSH 隧道和 HTTP 连接因空闲而超时。

**事件流式推送**：

```typescript
const stream = sessionPool.send(params.sessionId, params.message);
for await (const event of stream) {
    if (clientDisconnected) {
        sessionPool.bufferEvent(params.sessionId, event);
        continue;
    }
    res.write(`data: ${JSON.stringify(event)}\n\n`);
}
res.write("data: [DONE]\n\n");
res.end();
```

### handleHealthCheck

返回系统健康信息：

```typescript
{
    ok: true,
    sessions: number,              // 会话总数
    sessionsByStatus: {            // 按状态分类
        idle: number,
        busy: number,
    },
    uptime: number,                // 运行时间（秒）
    memory: {
        rss: number,               // RSS 内存 (MB)
        heapUsed: number,          // 已用堆内存 (MB)
        heapTotal: number,         // 总堆内存 (MB)
    },
    nodeVersion: string,           // Node.js 版本
    pid: number,                   // 进程 ID
}
```

### handleMonitorSessions

返回所有会话的详细信息，包含队列状态：

```typescript
{
    sessions: [{
        sessionId, path, status, mode, model,
        sdkSessionId, createdAt, lastActivityAt,
        queue: { userPending, responsePending, clientConnected }
    }],
    totalSessions: number,
    uptime: number,
}
```

## JSON-RPC 辅助函数

```typescript
function rpcSuccess(result: unknown, id?: string): RpcResponse {
    return { result, id };
}

function rpcError(code: number, message: string, id?: string): RpcResponse {
    return { error: { code, message }, id };
}
```

标准错误码：
- `-32600` — 无效请求（缺少 method）
- `-32601` — 方法不存在
- `-32602` — 无效参数
- `-32000` — 内部错误

## 优雅关闭

```typescript
async function shutdown(signal: string): Promise<void> {
    await sessionPool.destroyAll();  // 销毁所有会话，终止所有 Claude 进程
    process.exit(0);
}

process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));
```

## 与其他模块的关系

- **session-pool.ts** — 调用会话管理的所有方法
- **skill-manager.ts** — 在创建会话时调用 `syncToProject()`
- **types.ts** — 使用所有 RPC 参数类型定义
