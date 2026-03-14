# Bot 基类 (bot_base.py)

`bot_base.py` 定义了聊天 Bot 的抽象基类，包含所有命令处理逻辑和消息转发机制。Discord 和 Telegram Bot 都继承此基类。

**源文件**：`head/bot_base.py`

## 职责

1. 定义平台无关的 Bot 接口（抽象方法）
2. 实现命令分发逻辑（`/start`、`/exit`、`/mode` 等所有命令）
3. 实现消息转发和流式显示机制
4. 管理并发控制（防止同一频道同时处理多条消息）

## 类定义

```python
class BotBase(ABC):
    ssh: SSHManager                # SSH 管理器
    router: SessionRouter          # 会话路由器
    daemon: DaemonClient           # Daemon 客户端
    config: Config                 # 全局配置
    _streaming: set[str]           # 正在流式处理的频道 ID 集合
```

## 抽象方法

子类必须实现以下方法：

```python
@abstractmethod
async def send_message(self, channel_id: str, text: str) -> Any:
    """发送新消息到频道。返回平台消息对象。"""

@abstractmethod
async def edit_message(self, channel_id: str, message_obj: Any, text: str) -> None:
    """编辑已有消息。"""

@abstractmethod
async def start(self) -> None:
    """启动 Bot，连接到平台并开始监听。"""

@abstractmethod
async def stop(self) -> None:
    """停止 Bot。"""
```

## 命令分发

### handle_input(channel_id, text)

主入口方法。根据消息内容判断是命令还是普通消息：

- 以 `/` 开头 → 路由到 `_handle_command()`
- 其他 → 转发到 `_forward_message()`

### _handle_command(channel_id, text)

解析命令并分发到对应的处理函数：

| 命令 | 处理方法 |
|------|----------|
| `/start` | `cmd_start()` |
| `/resume` | `cmd_resume()` |
| `/ls`, `/list` | `cmd_ls()` |
| `/exit` | `cmd_exit()` |
| `/rm`, `/remove`, `/destroy` | `cmd_rm()` |
| `/mode` | `cmd_mode()` |
| `/status` | `cmd_status()` |
| `/interrupt` | `cmd_interrupt()` |
| `/health` | `cmd_health()` |
| `/monitor` | `cmd_monitor()` |
| `/help` | `cmd_help()` |

所有命令都有统一的异常处理：
- `DaemonConnectionError` → "Cannot connect to daemon"
- `DaemonError` → "Daemon error: ..."
- 其他异常 → 记录日志并显示错误

## 命令实现

### cmd_start(channel_id, args, silent_init=False)

创建新会话。`silent_init` 参数用于 Discord 斜杠命令（因为 Discord 已经发送了初始响应）。

**流程**：
1. 验证参数（需要 machine_id 和 path）
2. `ssh.ensure_tunnel()` — 建立 SSH 隧道
3. `ssh.sync_skills()` — 同步技能文件
4. `daemon.create_session()` — 在 Daemon 上创建会话
5. `router.register()` — 注册本地会话状态

### cmd_resume(channel_id, args)

恢复之前的会话。

**流程**：
1. `router.find_session_by_daemon_id()` — 查找会话记录
2. `ssh.ensure_tunnel()` — 建立隧道
3. `daemon.resume_session()` — 在 Daemon 上恢复
4. `router.register()` — 重新注册为活跃

### cmd_ls(channel_id, args)

列出机器或会话。支持两个子命令：
- `machine` / `machines` — 调用 `ssh.list_machines()`
- `session` / `sessions` — 调用 `router.list_sessions()`

### cmd_exit(channel_id)

分离当前会话。调用 `router.detach()` 并显示恢复命令。

### cmd_rm(channel_id, args)

销毁匹配的会话。先查找匹配的会话，然后逐个在 Daemon 上销毁并更新本地状态。

### cmd_mode(channel_id, args)

切换权限模式。接受 `auto`、`code`、`plan`、`ask` 和 `bypass`（映射到 `auto`）。

### cmd_interrupt(channel_id)

中断 Claude 当前操作。调用 `daemon.interrupt_session()`。

### cmd_health(channel_id, args)

检查 Daemon 健康状态。如果没有指定机器，会检查所有已连接的机器。

### cmd_monitor(channel_id, args)

查看会话监控信息。逻辑与 `cmd_health` 类似。

## 消息转发

### _forward_message(channel_id, text)

将用户消息转发给 Claude 会话并流式显示响应。

**并发控制**：使用 `self._streaming` 集合跟踪哪些频道正在处理。同一频道不允许并发处理，第二条消息会收到 "Claude is still processing" 提示。

**流式显示机制**：

```python
buffer = ""           # 文本累积缓冲区
current_msg = None    # 当前正在编辑的消息对象
last_update = time.time()
```

事件处理循环：

| 事件类型 | 处理方式 |
|---------|---------|
| `ping` | 忽略（Daemon 心跳） |
| `partial` | 累积到 `buffer`，每 1.5 秒更新消息（末尾添加 `▌` 光标） |
| `text` | 完整文本块，替换当前消息或发送新消息 |
| `tool_use` | 格式化工具使用信息并发送 |
| `result` | 保存 `sdk_session_id` |
| `system` | 首次连接时显示模型信息 |
| `queued` | 通知用户消息已排队 |
| `error` | 显示错误信息 |

**缓冲区刷新**：当 `buffer` 长度超过 1800 字符时，完成当前消息并开始新消息，避免超过平台消息长度限制。

**最终刷新**：流结束后，如果 `buffer` 中还有内容，发送最后一条消息。

## 常量

```python
STREAM_UPDATE_INTERVAL = 1.5    # 流式更新间隔（秒）
STREAM_BUFFER_FLUSH_SIZE = 1800 # 缓冲区刷新阈值（字符）
```

## 与其他模块的关系

- **ssh_manager.py** — 建立隧道、同步技能、列出机器
- **session_router.py** — 会话状态管理
- **daemon_client.py** — RPC 通信
- **message_formatter.py** — 格式化输出
- **bot_discord.py** / **bot_telegram.py** — 继承此基类，实现平台特定方法
