# RPC 服务器（server.rs）

**文件：** `src/daemon/server.rs`

基于 Axum 的 JSON-RPC 服务器，为所有守护进程操作提供 `POST /rpc` 端点，并为 `session.send` 提供 SSE 流式响应。

## 用途

- 提供统一的 JSON-RPC 入口
- 根据 `method` 字段路由到具体处理器
- 为 `session.send` 返回 SSE（Server-Sent Events）流
- 发送 keepalive ping，避免连接空闲超时
- 在关闭时触发会话与子进程清理

## 主要状态

`AppState` 持有：
- `SessionPool`
- `SkillManager`
- `start_time`
- `shutdown` 通知器
- `config`
- `token_store`

## 方法路由

当前支持的方法：
- `session.create`
- `session.send`
- `session.resume`
- `session.destroy`
- `session.list`
- `session.set_mode`
- `session.set_model`
- `session.interrupt`
- `session.queue_stats`
- `session.reconnect`
- `health.check`
- `monitor.sessions`

## SSE 流（session.send）

`handle_send_message()` 会把 `SessionPool` 返回的事件流包装成 SSE：

- `Content-Type: text/event-stream`
- `Cache-Control: no-cache`
- `X-Accel-Buffering: no`

服务器会额外：
- 每 30 秒发送一个 `ping` 事件
- 在客户端断连时调用 `session_pool.client_disconnect()`
- 缓冲剩余事件，供 `session.reconnect` 使用
- 在正常结束时发送 `[DONE]`

## 健康检查

`handle_health_check()` 返回：

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

其中 `memory.heapUsed` / `memory.heapTotal` 当前是基于 RSS 的近似值，`version` 来自守护进程包版本。

## 与其他模块的关系

- 使用 **SessionPool** 处理会话生命周期与流式事件
- 使用 **SkillManager** 在 `session.create` 时同步说明/技能
- 使用 **types.rs** 中的请求、响应和模式类型

