# 类型定义（types.rs）

**文件：** `src/daemon/types.rs`

守护进程 RPC 协议、会话管理和流事件的核心类型定义。

## 用途

- 定义 JSON-RPC 请求/响应结构
- 定义会话状态和权限模式
- 定义 SSE 通信中的 `StreamEvent`
- 定义 `session.list` / `monitor.sessions` / `health.check` 等接口返回结构

## RPC 协议类型

### `RpcRequest`

```rust
pub struct RpcRequest {
    pub method: Option<String>,
    pub params: Option<Value>,
    pub id: Option<String>,
}
```

### `RpcResponse`

```rust
pub struct RpcResponse {
    pub result: Option<Value>,
    pub error: Option<RpcError>,
    pub id: Option<String>,
}

pub struct RpcError {
    pub code: i32,
    pub message: String,
}
```

## 会话相关类型

### `SessionStatus`

- `idle`
- `busy`
- `error`
- `destroyed`

### `PermissionMode`

- `auto`
- `code`
- `plan`
- `ask`

只有 `auto` 会映射到 Claude CLI 标志 `--dangerously-skip-permissions`；其余模式主要是上层语义。

### `SessionInfo`

用于 `session.list` / `monitor.sessions` 的可序列化快照，字段名使用 `camelCase`：

- `sessionId`
- `path`
- `status`
- `mode`
- `cliType`
- `sdkSessionId`
- `model`
- `createdAt`
- `lastActivityAt`

### `QueueStats`

- `userPending`
- `responsePending`
- `clientConnected`

## 流事件类型

`StreamEvent` 使用带 `type` 标签的枚举序列化：

- `text`
- `tool_use`
- `result`
- `queued`
- `error`
- `system`
- `partial`
- `ping`
- `interrupted`

其中：
- `result` / `error` / `interrupted` 是终止事件
- `system` 和 `result` 都可能携带 `session_id`

## 健康检查与监控

### `health.check`

当前返回：

```json
{
  "ok": true,
  "sessions": 3,
  "sessionsByStatus": {"idle": 2, "busy": 1},
  "uptime": 3600,
  "memory": {
    "rss": 45,
    "heapUsed": 20,
    "heapTotal": 30
  },
  "version": "0.2.22",
  "pid": 12345
}
```

### `monitor.sessions`

返回每个会话的 `SessionInfo` 加上队列统计信息。

## 与其他模块的关系

- **src/daemon/server.rs** 使用请求/响应与模式类型
- **src/daemon/session_pool.rs** 使用 `SessionStatus`、`PermissionMode`、`StreamEvent`、`SessionInfo`、`QueueStats`
- **src/daemon/message_queue.rs** 使用 `StreamEvent` 和 `QueueStats`
- **src/daemon/cli_adapter/** 使用 `PermissionMode` 和 `StreamEvent`

