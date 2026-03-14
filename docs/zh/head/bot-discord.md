# Discord Bot (bot_discord.py)

`bot_discord.py` 实现了 Discord 平台的 Bot，使用 discord.py v2 的斜杠命令、自动补全和心跳状态更新。

**源文件**：`head/bot_discord.py`

## 职责

1. 实现 Discord 平台特定的消息发送和编辑
2. 注册所有斜杠命令（app_commands）及其自动补全
3. 管理打字指示器（typing indicator）
4. 实现心跳状态更新机制（避免 Discord 超时）
5. 处理延迟交互（deferred interaction）

## 类结构

```python
class DiscordBot(BotBase):
    discord_config: DiscordConfig         # Discord 配置
    bot: commands.Bot                     # discord.py Bot 实例
    _channels: dict[str, Messageable]     # 频道缓存
    _typing_tasks: dict[str, Task]        # 打字指示器任务
    _heartbeat_msgs: dict[str, Message]   # 心跳消息缓存
    _deferred_interactions: dict[str, Interaction]  # 延迟交互
    _init_shown: set[str]                 # 已显示初始化信息的会话
```

## Discord 特性

### 斜杠命令（Slash Commands）

所有命令都注册为 Discord app_commands，用户在聊天窗口输入 `/` 时会看到命令列表和参数提示。

注册的命令：

| 命令 | 参数 | 补全 |
|------|------|------|
| `/start` | `machine`, `path` | 两者都有自动补全 |
| `/resume` | `session_id` | 无 |
| `/ls` | `target` (choice), `machine` | `target` 有预定义选项，`machine` 有补全 |
| `/exit` | 无 | — |
| `/rm` | `machine`, `path` | `machine` 有补全 |
| `/mode` | `mode` (choice) | 4 个预定义选项 |
| `/status` | 无 | — |
| `/health` | `machine` (可选) | 有补全 |
| `/monitor` | `machine` (可选) | 有补全 |
| `/help` | 无 | — |

### 自动补全（Autocomplete）

机器名自动补全会自动排除纯跳板机（被用作 `proxy_jump` 的机器）。

路径自动补全基于所选机器的 `default_paths` 配置。如果还没有选择机器，会聚合所有机器的路径并去重。

```python
@slash_start.autocomplete("machine")
async def start_machine_autocomplete(interaction, current):
    # 排除跳板机
    jump_hosts = {m.proxy_jump for m in self.config.machines.values() if m.proxy_jump}
    machines = [
        mid for mid in self.config.machines
        if mid not in jump_hosts and current.lower() in mid.lower()
    ]
    return [app_commands.Choice(name=m, value=m) for m in machines][:25]
```

### 模式选择框

`/mode` 命令使用预定义的 `Choice` 列表，每个选项附带说明文字：

```python
@app_commands.choices(mode=[
    Choice(name="bypass - Full auto (skip all permissions)", value="auto"),
    Choice(name="code - Auto accept edits, confirm bash", value="code"),
    Choice(name="plan - Read-only analysis", value="plan"),
    Choice(name="ask - Confirm everything", value="ask"),
])
```

### 延迟交互（Deferred Interaction）

部分命令使用 `interaction.response.defer()` 延迟响应，避免 Discord 的 3 秒交互超时。

延迟后，第一次调用 `send_message()` 时会自动使用 `interaction.followup.send()` 而非 `channel.send()`。

```python
def _defer_and_register(self, interaction):
    channel_id = f"discord:{interaction.channel_id}"
    self._channels[channel_id] = interaction.channel
    self._deferred_interactions[channel_id] = interaction
    return channel_id
```

## 消息处理

### on_message 事件

处理非命令的普通消息。过滤条件：
1. 忽略 Bot 自身的消息
2. 忽略其他 Bot 的消息
3. 忽略以 `/` 开头的消息（由斜杠命令处理）
4. 如果配置了 `allowed_channels`，只在允许的频道中响应

通过的消息会被转发到 `_forward_message_with_heartbeat()`。

### 频道 ID 格式

Discord 频道使用 `discord:{channel_id}` 格式的内部 ID，例如 `discord:123456789012345678`。

## 打字指示器

在 Claude 处理消息期间，显示 "Bot is typing..." 指示器。

```python
async def _start_typing(self, channel_id):
    async def typing_loop():
        while True:
            await channel.typing()      # 触发打字指示器
            await asyncio.sleep(8)       # Discord 打字指示器持续约 10 秒
    task = asyncio.create_task(typing_loop())
```

## 心跳状态更新

这是 Discord Bot 特有的功能。在 Claude 处理消息期间，每 25 秒发送一条状态更新消息，告知用户 Claude 正在做什么。

```python
HEARTBEAT_INTERVAL = 25  # 秒
```

心跳消息格式示例：
```
[1m30s] Claude is working... Using tool: Write
[2m05s] Claude is working... Writing response...
[3m10s] Claude is working... Thinking...
```

**event_tracker**：心跳循环和消息流式处理共享一个字典，用于跟踪 Claude 的当前状态：

```python
event_tracker = {
    "last_event_type": "",    # 最近收到的事件类型
    "tool_name": "",          # 当前使用的工具名
    "done": False,            # 是否处理完成
    "partial_len": 0,         # 累积的部分响应长度
}
```

状态判断逻辑：
- 有 `tool_name` → "Using tool: **{name}**"
- `partial` 事件且有内容 → "Writing response..."
- `tool_use` / `tool_result` 之后 → "Processing tool results..."
- 其他 → "Thinking..."

心跳消息在处理完成后会被自动删除。

## 消息发送

### send_message(channel_id, text) -> Message

发送消息到 Discord 频道。

**特殊逻辑**：
1. 如果有待消费的延迟交互，使用 `interaction.followup.send()`
2. 否则使用 `channel.send()`
3. 自动按 2000 字符限制分割长消息
4. 发送失败时尝试去除格式化（`**`、`` ` ``）后重发

### edit_message(channel_id, message_obj, text)

编辑已有消息。超过 2000 字符的内容会被截断。

编辑失败时（例如消息太旧），会尝试发送一条新消息作为后备。

## 初始化信息去重

使用 `_init_shown` 集合跟踪已显示 "Connected to {model}" 信息的会话，避免同一会话多次显示初始化信息。

```python
if daemon_sid not in self._init_shown:
    self._init_shown.add(daemon_sid)
    await self.send_message(channel_id, f"Connected to **{model}** | Mode: **{mode_str}**")
```

## 与其他模块的关系

- **bot_base.py** — 继承所有命令处理逻辑
- **message_formatter.py** — 使用 `split_message()`、`format_error()`、`display_mode()`
- **config.py** — 使用 `DiscordConfig`
