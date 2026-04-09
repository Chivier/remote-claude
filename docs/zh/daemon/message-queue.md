# 消息队列（message_queue.rs）

**文件：** `src/daemon/message_queue.rs`

每会话消息队列，承担三项职责：在 CLI 繁忙时缓冲用户消息、在 SSH/SSE 连接断开时缓冲响应，以及追踪客户端连接状态。

## 用途

- **用户消息缓冲**：当前消息处理期间，新消息会排队并在之后按顺序执行
- **响应缓冲**：如果 SSE 流中途断开，事件会被缓冲，客户端重连时可重放
- **客户端连接追踪**：决定是否应当缓冲响应事件

## 结构

```rust
pub struct MessageQueue {
    user_pending: VecDeque<QueuedUserMessage>,
    response_pending: VecDeque<QueuedResponse>,
    client_connected: bool,
}
```

## 关键方法

### `enqueue_user(message) -> usize`

将用户消息加入队尾，返回新的队列长度（作为 `queued.position`）。

### `dequeue_user() -> Option<QueuedUserMessage>`

取出下一条等待处理的用户消息。由 `SessionPool` 在当前消息完成后调用。

### `buffer_response(event, force)`

缓冲响应事件：
- `force = false` 时，仅在客户端已断开时缓冲
- `force = true` 时，无论当前状态如何都强制缓冲；用于 `server.rs` 已检测到断连但 `SessionPool` 尚未收到通知的场景

### `on_client_disconnect()` / `on_client_reconnect()`

更新客户端连接状态。`on_client_reconnect()` 会返回并清空所有缓冲事件。

### `stats() -> QueueStats`

返回：
- `user_pending`
- `response_pending`
- `client_connected`

供 `/status`、`/monitor` 和 RPC 监控接口使用。

## 与其他模块的关系

- **src/daemon/session_pool.rs** 为每个会话创建一个 `MessageQueue`
- **src/daemon/server.rs** 在 SSE 断连和 `session.reconnect` 路径中使用它
- 类型定义来自 **src/daemon/types.rs**

