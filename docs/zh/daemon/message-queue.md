# 消息队列 (message-queue.ts)

`message-queue.ts` 实现了每个会话独立的消息队列，负责用户消息缓冲、响应事件缓冲和客户端连接状态跟踪。

**源文件**：`daemon/src/message-queue.ts`

## 职责

1. **用户消息缓冲** — 当 Claude 正在处理一条消息时，后续消息自动排队等待
2. **响应缓冲** — 当 SSH 连接断开时，缓存 Claude 产生的响应事件，重连后回放
3. **连接状态跟踪** — 追踪 Head Node 客户端的连接状态

## 类结构

```typescript
class MessageQueue {
    private userPending: QueuedUserMessage[];    // 待处理的用户消息
    private responsePending: QueuedResponse[];    // 缓冲的响应事件
    private _clientConnected: boolean;            // 客户端连接状态
}
```

## 用户消息缓冲

当 Claude 正在处理某条消息（`session.processing = true`）时，`SessionPool.send()` 会将新消息放入队列而非立即处理。

### enqueueUser(message: string) -> number

将用户消息加入队列。返回当前队列中的消息数量（即新消息的位置）。

```typescript
enqueueUser(message: string): number {
    this.userPending.push({ message, timestamp: Date.now() });
    return this.userPending.length;  // 位置信息
}
```

这个位置信息会通过 `{ type: "queued", position }` 事件返回给用户，告知消息已排队。

### dequeueUser() -> QueuedUserMessage | null

从队列头部取出下一条消息。在当前消息处理完成后，`SessionPool` 会调用此方法自动处理下一条。

### hasUserPending() -> boolean

检查是否有待处理的用户消息。

### userQueueLength (getter)

返回待处理的用户消息数量。

## 响应缓冲

当 SSH 隧道断开或 Head Node 的 HTTP 客户端断连时，Claude 可能仍在继续处理消息。此时产生的响应事件会被缓冲，等待客户端重连后一次性回放。

### bufferResponse(event: StreamEvent, force: boolean = false)

缓冲一个响应事件。

```typescript
bufferResponse(event: StreamEvent, force: boolean = false): void {
    if (force || !this._clientConnected) {
        this.responsePending.push({ event, timestamp: Date.now() });
    }
}
```

- 默认只在客户端断连时缓冲
- `force = true` 时无论连接状态都会缓冲（用于 server.ts 检测到写入失败的情况）

### replayResponses() -> StreamEvent[]

回放所有缓冲的响应事件，并清空缓冲区。

```typescript
replayResponses(): StreamEvent[] {
    const events = this.responsePending.map((r) => r.event);
    this.responsePending = [];
    return events;
}
```

### hasResponsesPending() -> boolean

检查是否有缓冲的响应事件。

## 连接状态管理

### clientConnected (getter)

返回当前客户端的连接状态。

### onClientDisconnect()

标记客户端断连。之后的响应事件会自动被缓冲。

调用时机：
- `server.ts` 的 SSE 响应检测到客户端断开（`res.on("close")`）
- `server.ts` 写入 SSE 数据失败

### onClientReconnect() -> StreamEvent[]

标记客户端重连，并返回在断连期间缓冲的所有事件。

```typescript
onClientReconnect(): StreamEvent[] {
    this._clientConnected = true;
    return this.replayResponses();  // 回放并清空
}
```

调用时机：
- `session.reconnect` RPC 方法被调用
- `session.resume` RPC 方法被调用

## 清理

### clear()

清空所有队列（用户消息和响应缓冲）。在会话销毁或中断时调用。

### stats()

返回队列统计信息：

```typescript
stats(): {
    userPending: number;        // 待处理用户消息数
    responsePending: number;    // 缓冲响应事件数
    clientConnected: boolean;   // 客户端是否连接
}
```

## 数据流示例

### 正常流程

```
用户消息 A → SessionPool.send() → processMessage() → 流式响应 → 完成
用户消息 B → SessionPool.send() → processMessage() → 流式响应 → 完成
```

### Claude 忙时排队

```
用户消息 A → SessionPool.send() → processMessage() → 处理中...
用户消息 B → SessionPool.send() → queue.enqueueUser(B) → yield {type: "queued", position: 1}
用户消息 C → SessionPool.send() → queue.enqueueUser(C) → yield {type: "queued", position: 2}
                                                     ...消息 A 处理完成...
                              → queue.dequeueUser() → processMessage(B) → 处理中...
                                                     ...消息 B 处理完成...
                              → queue.dequeueUser() → processMessage(C) → 流式响应 → 完成
```

### SSH 断连恢复

```
消息处理中... → 客户端断连 → queue.onClientDisconnect()
                            → 响应事件被缓冲到 responsePending
                            ...一段时间后...
客户端重连 → session.reconnect RPC → queue.onClientReconnect()
                                   → 返回所有缓冲事件
                                   → 客户端重新显示这些事件
```

## 与其他模块的关系

- **session-pool.ts** — 每个 InternalSession 持有一个 MessageQueue 实例
- **server.ts** — 通过 SessionPool 间接调用队列方法
- **types.ts** — 使用 `QueuedUserMessage`、`QueuedResponse`、`StreamEvent` 类型
