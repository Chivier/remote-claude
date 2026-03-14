# SSE 流事件

当调用 `session.send` 方法时，Daemon 使用 SSE（Server-Sent Events）协议流式推送 Claude 的响应。本文档描述所有可能的事件类型。

## SSE 协议基础

响应使用以下 HTTP 头：

```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

每个事件的格式：

```
data: {"type": "event_type", ...}\n\n
```

流结束时发送：

```
data: [DONE]\n\n
```

## 事件类型

### system

系统事件，通常在 Claude 进程启动时发送。

**init 子类型**：

```json
{
    "type": "system",
    "subtype": "init",
    "session_id": "sdk-session-uuid",
    "model": "claude-sonnet-4-20250514"
}
```

| 字段 | 说明 |
|------|------|
| `subtype` | 事件子类型，`init` 表示初始化 |
| `session_id` | Claude SDK 会话 ID |
| `model` | 使用的模型名称 |

Head Node 收到此事件后会在聊天中显示 "Connected to {model} | Mode: {mode}"。

**其他 system 事件**：

```json
{
    "type": "system",
    "raw": { ... }
}
```

不被识别的系统事件会保留原始数据（`raw` 字段），但不会触发特殊处理。

---

### partial

流式文本增量。Claude 逐字生成文本时，通过 `partial` 事件实时推送增量内容。

```json
{
    "type": "partial",
    "content": "这是"
}
```

```json
{
    "type": "partial",
    "content": "一段"
}
```

```json
{
    "type": "partial",
    "content": "流式文本"
}
```

| 字段 | 说明 |
|------|------|
| `content` | 文本增量（可能只有一个字或几个字） |

Head Node 将这些增量累积到缓冲区中，每 1.5 秒更新一次聊天消息（显示 `▌` 光标表示仍在输入）。

**来源**：
- Claude CLI 的 `stream_event` 类型中 `content_block_delta` 的 `text` 字段
- Claude CLI 的 `stream_event` 类型中 `content_block_delta` 的 `partial_json` 字段

---

### text

完整的文本块。在 Claude 完成一个完整的文本内容块时发送。

```json
{
    "type": "text",
    "content": "这是 Claude 的完整回复文本...",
    "raw": { ... }
}
```

| 字段 | 说明 |
|------|------|
| `content` | 完整文本内容 |
| `raw` | Claude CLI 原始消息（可选） |

**来源**：Claude CLI 的 `assistant` 类型消息中 `content` 数组的 `text` 块。

> **注意**：`text` 事件和 `partial` 事件可能同时存在。`partial` 提供实时增量，`text` 提供完整内容。Head Node 收到 `text` 时会用它替换之前从 `partial` 累积的内容。

---

### tool_use

工具调用事件。当 Claude 决定使用工具时发送。

**工具开始**：

```json
{
    "type": "tool_use",
    "tool": "Write",
    "raw": { ... }
}
```

**工具调用详情**：

```json
{
    "type": "tool_use",
    "tool": "Bash",
    "input": {
        "command": "npm install express"
    },
    "raw": { ... }
}
```

**工具进度更新**：

```json
{
    "type": "tool_use",
    "tool": "Bash",
    "message": "Running command..."
}
```

| 字段 | 说明 |
|------|------|
| `tool` | 工具名称（如 Write、Read、Bash、Glob、Grep 等） |
| `input` | 工具输入参数（可选） |
| `message` | 工具执行状态消息（可选） |

**来源**：
- Claude CLI 的 `assistant` 消息中 `tool_use` 类型的 content block
- Claude CLI 的 `stream_event` 中 `content_block_start` 的 `tool_use` block
- Claude CLI 的 `tool_progress` 类型消息

Head Node 会将工具使用格式化为：
```
**[Tool: Bash]**
```npm install```
```

---

### result

完成事件。当 Claude 处理完一条消息后发送。

```json
{
    "type": "result",
    "session_id": "sdk-session-uuid-for-resume",
    "raw": {
        "type": "result",
        "duration_ms": 5230,
        "usage": {
            "input_tokens": 1234,
            "output_tokens": 567
        }
    }
}
```

| 字段 | 说明 |
|------|------|
| `session_id` | Claude SDK 会话 ID，用于后续 `--resume` |
| `raw` | 原始数据，包含 duration 和 token 使用量 |

Head Node 收到此事件后会将 `session_id` 保存到 SessionRouter 中，供下次消息使用 `--resume` 恢复上下文。

---

### queued

消息已排队事件。当用户发送消息但 Claude 正忙时返回。

```json
{
    "type": "queued",
    "position": 1
}
```

| 字段 | 说明 |
|------|------|
| `position` | 在队列中的位置（1 表示队列中的第一个） |

Head Node 会通知用户：
```
Message queued (position: 1). Claude is busy with a previous request.
```

收到此事件后 SSE 流会立即结束。当排队的消息被实际处理时，如果客户端仍然连接，会通过新的 SSE 流接收响应。

---

### error

错误事件。

```json
{
    "type": "error",
    "message": "Claude process exited abnormally (code=1, signal=null)"
}
```

| 字段 | 说明 |
|------|------|
| `message` | 错误描述 |

常见错误来源：
- Claude CLI 进程非正常退出
- Claude CLI 进程启动失败
- 内部错误

---

### ping

心跳事件。Daemon 每 30 秒发送一次，用于防止连接超时。

```json
{
    "type": "ping"
}
```

Head Node 收到 `ping` 事件后会忽略它，不做任何处理。心跳的作用是保持 SSH 隧道和 HTTP 连接活跃。

---

### interrupted

操作被中断事件。当用户通过 `/interrupt` 命令中断 Claude 时可能出现。

```json
{
    "type": "interrupted"
}
```

这是一个终端事件——收到后 SSE 流会结束。

## 事件流示例

### 典型的文本回复

```
data: {"type":"system","subtype":"init","model":"claude-sonnet-4-20250514","session_id":"sdk-123"}

data: {"type":"partial","content":"你"}

data: {"type":"partial","content":"好"}

data: {"type":"partial","content":"！我"}

data: {"type":"partial","content":"可以"}

data: {"type":"partial","content":"帮你"}

data: {"type":"text","content":"你好！我可以帮你分析代码。请把代码发给我。"}

data: {"type":"result","session_id":"sdk-123"}

data: [DONE]
```

### 包含工具调用的回复

```
data: {"type":"system","subtype":"init","model":"claude-sonnet-4-20250514","session_id":"sdk-123"}

data: {"type":"partial","content":"让我看看"}

data: {"type":"partial","content":"这个文件..."}

data: {"type":"tool_use","tool":"Read","input":{"file_path":"/src/main.py"}}

data: {"type":"tool_use","tool":"Read","message":"Reading file..."}

data: {"type":"partial","content":"这段代码"}

data: {"type":"partial","content":"有一个bug..."}

data: {"type":"text","content":"这段代码有一个bug，我来帮你修复。"}

data: {"type":"tool_use","tool":"Write","input":{"file_path":"/src/main.py","content":"..."}}

data: {"type":"text","content":"已经修复了这个问题。"}

data: {"type":"result","session_id":"sdk-123"}

data: [DONE]
```

### Claude 忙时排队

```
data: {"type":"queued","position":1}

data: [DONE]
```

### 空闲超时

如果 Claude 长时间不产出事件，Head Node 会超时：

```
data: {"type":"system","subtype":"init","model":"claude-sonnet-4-20250514"}

data: {"type":"ping"}

data: {"type":"ping"}

... (长时间无 partial/text 事件)

// Head Node 端超时，产生本地错误事件:
// {"type":"error","message":"Stream idle timeout (300s with no events). Session may be stuck."}
```

## 终端事件

以下事件类型是终端事件，收到后事件流应结束：

- `result` — 正常完成
- `error` — 出错
- `interrupted` — 被中断

收到终端事件后，Daemon 会发送 `data: [DONE]` 并关闭 SSE 连接。
