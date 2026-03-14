# Daemon 客户端 (daemon_client.py)

`daemon_client.py` 实现了与远程 Daemon 通信的 JSON-RPC 客户端，支持普通请求和 SSE 流式响应。

**源文件**：`head/daemon_client.py`

## 职责

1. 通过 SSH 隧道向远程 Daemon 发送 JSON-RPC 请求
2. 处理 SSE（Server-Sent Events）流式响应
3. 提供所有 RPC 方法的类型安全封装
4. 错误处理和连接管理

## DaemonClient 类

```python
class DaemonClient:
    timeout: int = 300           # 默认超时（秒）
    _session: aiohttp.ClientSession  # HTTP 会话（懒初始化）
```

### 构造和清理

```python
client = DaemonClient(timeout=300)  # 5 分钟默认超时

# 使用完毕后关闭
await client.close()
```

HTTP 会话使用 `aiohttp.ClientSession`，支持懒初始化和自动重建（如果会话已关闭）。

### RPC 端点

所有请求发送到 `http://127.0.0.1:{local_port}/rpc`，其中 `local_port` 是 SSH 隧道的本地端口。

## 方法列表

### 会话管理

#### create_session(local_port, path, mode) -> str

创建新的 Claude 会话。

```python
session_id = await client.create_session(19100, "/home/user/project", "auto")
# 返回: "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
```

#### send_message(local_port, session_id, message, idle_timeout) -> AsyncIterator

发送消息并流式接收 Claude 的响应。返回异步迭代器，逐个产出 SSE 事件。

```python
async for event in client.send_message(19100, session_id, "Hello Claude"):
    if event["type"] == "partial":
        print(event["content"], end="")  # 流式文本
    elif event["type"] == "result":
        print("Done!")
```

**超时设置**：
- 总超时：900 秒（15 分钟）
- 空闲超时：`idle_timeout` 参数，默认 300 秒（5 分钟）。在每次收到事件时重置
- 如果空闲超时触发，会产出一个 `error` 事件

**SSE 解析**：
- 读取每一行，过滤空行
- 解析 `data: ` 前缀的行
- `data: [DONE]` 表示流结束
- 每个 data 行被解析为 JSON 对象并产出

**错误处理**：
- `asyncio.TimeoutError` → 产出 error 事件（空闲超时）
- `aiohttp.ClientError` → 产出 error 事件（连接错误）

#### resume_session(local_port, session_id, sdk_session_id) -> dict

恢复之前的会话。

```python
result = await client.resume_session(19100, "session-id", "sdk-session-id")
# result = {"ok": True, "fallback": False}
```

`sdk_session_id` 是可选的，如果提供，Daemon 会使用它来恢复完整的对话上下文。

#### destroy_session(local_port, session_id) -> bool

销毁会话，终止关联的 Claude 进程。

#### list_sessions(local_port) -> list[dict]

列出远程 Daemon 上的所有会话。

#### set_mode(local_port, session_id, mode) -> bool

设置会话的权限模式。

#### interrupt_session(local_port, session_id) -> dict

中断当前操作。向 Claude CLI 进程发送 SIGTERM 信号。

```python
result = await client.interrupt_session(19100, "session-id")
# result = {"ok": True, "interrupted": True}
# interrupted=True 表示确实有正在运行的操作被中断
# interrupted=False 表示 Claude 当前空闲
```

### 监控方法

#### health_check(local_port) -> dict

检查 Daemon 健康状态。返回会话数、内存使用、运行时间等信息。

#### monitor_sessions(local_port) -> dict

获取所有会话的详细监控信息，包括队列状态。

### 连接恢复

#### reconnect_session(local_port, session_id) -> list[dict]

重新连接到会话并获取在断连期间缓冲的事件。

#### get_queue_stats(local_port, session_id) -> dict

获取会话的消息队列统计信息。

```python
stats = await client.get_queue_stats(19100, "session-id")
# stats = {"userPending": 0, "responsePending": 2, "clientConnected": True}
```

## 异常类

### DaemonError

Daemon RPC 返回的业务错误。

```python
class DaemonError(Exception):
    code: int      # 错误码
    message: str   # 错误消息
```

当 RPC 响应包含 `error` 字段时抛出。

### DaemonConnectionError

无法连接到 Daemon。

```python
class DaemonConnectionError(Exception):
    pass
```

当 HTTP 请求失败（网络错误、连接拒绝等）时抛出。通常表示 SSH 隧道已断开或 Daemon 未运行。

## 内部实现

### _rpc_call(local_port, method, params) -> dict

底层 RPC 调用方法。

```python
# 请求格式
{"method": "session.create", "params": {"path": "/home/user/project", "mode": "auto"}}

# 成功响应
{"result": {"sessionId": "..."}}

# 错误响应
{"error": {"code": -32602, "message": "Missing required param: path"}}
```

超时设置为 30 秒（适用于非流式请求）。

### _get_session() -> aiohttp.ClientSession

获取或创建 aiohttp 会话。如果现有会话已关闭，会创建新的。

## 与其他模块的关系

- **bot_base.py** — 调用所有 RPC 方法（create_session、send_message 等）
- **main.py** — 实例化 `DaemonClient` 并在关闭时调用 `close()`
- **session_router.py** — 提供 `daemon_session_id` 供 DaemonClient 使用
- **ssh_manager.py** — 提供 `local_port` 供 DaemonClient 连接
