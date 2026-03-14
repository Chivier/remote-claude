# Telegram Bot (bot_telegram.py)

`bot_telegram.py` 实现了 Telegram 平台的 Bot，使用 python-telegram-bot v20+ 的异步接口。

**源文件**：`head/bot_telegram.py`

## 职责

1. 实现 Telegram 平台特定的消息发送和编辑
2. 注册命令处理器和消息处理器
3. 管理 Telegram Bot 生命周期（轮询模式）
4. 用户权限验证

## 类结构

```python
class TelegramBot(BotBase):
    telegram_config: TelegramConfig       # Telegram 配置
    _app: Application                     # python-telegram-bot 应用
    _bot: Bot                             # Telegram Bot 实例
    _last_messages: dict[str, int]        # 频道 ID -> 最后消息 ID 缓存
```

## 用户权限

### _is_allowed_user(user_id)

检查 Telegram 用户是否被允许使用 Bot。

- 如果 `allowed_users` 列表为空，允许所有用户
- 否则只允许列表中的用户 ID

```python
def _is_allowed_user(self, user_id: int) -> bool:
    if not self.telegram_config.allowed_users:
        return True  # 无限制
    return user_id in self.telegram_config.allowed_users
```

## 频道 ID 格式

Telegram 使用 `telegram:{chat_id}` 格式的内部 ID，例如 `telegram:123456789`。

```python
def _channel_id(self, chat_id: int) -> str:
    return f"telegram:{chat_id}"

def _chat_id_from_channel(self, channel_id: str) -> int:
    return int(channel_id.split(":")[1])
```

## 消息处理器

### 命令处理器

注册以下命令的处理器：

```python
command_names = [
    "start", "resume", "ls", "list", "exit", "rm", "remove",
    "destroy", "mode", "status", "health", "monitor", "help"
]
```

每个命令都使用 `CommandHandler` 注册，并路由到 `_handle_telegram_command()`。

由于 python-telegram-bot 的 `CommandHandler` 在某些情况下可能去除命令前缀，处理函数会确保消息以 `/` 开头后再传递给 `handle_input()`。

### 消息处理器

非命令的文本消息通过 `MessageHandler` 处理：

```python
self._app.add_handler(MessageHandler(
    filters.TEXT & ~filters.COMMAND,
    self._handle_telegram_message,
))
```

所有非命令消息都转发到 `handle_input()`，进而由基类的 `_forward_message()` 转发给 Claude。

## 消息发送

### send_message(channel_id, text) -> Message

发送消息到 Telegram 聊天。

**特点**：
- Telegram 单条消息限制 **4096 字符**（比 Discord 的 2000 多一倍）
- 使用 `split_message(text, max_len=4096)` 分割长消息
- 首先尝试使用 Markdown 格式发送（`ParseMode.MARKDOWN`）
- 如果 Markdown 解析失败，自动降级为纯文本发送
- 缓存最后一条消息的 `message_id`

```python
try:
    last_msg = await self._bot.send_message(
        chat_id=chat_id,
        text=chunk,
        parse_mode=ParseMode.MARKDOWN,
    )
except Exception:
    # 降级：无格式发送
    last_msg = await self._bot.send_message(
        chat_id=chat_id,
        text=chunk,
    )
```

### edit_message(channel_id, message_obj, text)

编辑已有消息。

**特点**：
- 超过 4096 字符的内容会被截断
- 同样使用 Markdown 优先，失败后降级为纯文本
- 从 `message_obj` 的 `message_id` 属性获取消息 ID

## 启动和停止

### start()

启动 Telegram Bot。使用轮询（polling）模式接收消息。

```python
async def start(self):
    self._app = Application.builder().token(token).build()
    self._bot = self._app.bot

    # 注册处理器...

    await self._app.initialize()
    await self._app.start()
    await self._app.updater.start_polling()
```

启动后 Bot 开始轮询 Telegram 服务器获取更新。主事件循环由 `main.py` 管理。

### stop()

停止 Telegram Bot。

```python
async def stop(self):
    if self._app.updater:
        await self._app.updater.stop()
    await self._app.stop()
    await self._app.shutdown()
```

按顺序：停止轮询器 → 停止应用 → 清理资源。

## 与 Discord Bot 的区别

| 特性 | Discord Bot | Telegram Bot |
|------|------------|--------------|
| 命令方式 | 斜杠命令 (app_commands) | CommandHandler |
| 自动补全 | 有（机器名、路径） | 无 |
| 消息长度限制 | 2000 字符 | 4096 字符 |
| 格式化 | Discord Markdown | Telegram Markdown |
| 打字指示器 | 有（typing loop） | 无 |
| 心跳更新 | 有（每 25 秒） | 无 |
| 延迟响应 | 有（defer） | 无 |
| 权限控制 | 频道 ID 列表 | 用户 ID 列表 |
| 消息接收 | WebSocket | 轮询 (polling) |

## 与其他模块的关系

- **bot_base.py** — 继承所有命令处理逻辑和消息转发
- **message_formatter.py** — 使用 `split_message(text, max_len=4096)`
- **config.py** — 使用 `TelegramConfig`
