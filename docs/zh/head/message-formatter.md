# 消息格式化 (message_formatter.py)

`message_formatter.py` 提供消息分割和格式化工具函数，用于将各种数据格式化为适合在 Discord/Telegram 中显示的文本。

**源文件**：`head/message_formatter.py`

## 职责

1. 智能分割长消息（避免拆断代码块）
2. 格式化各种输出（机器列表、会话列表、状态信息、健康报告、监控数据）
3. 权限模式的显示名称映射

## 权限模式显示名称

```python
MODE_DISPLAY_NAMES = {
    "auto": "bypass",
    "code": "code",
    "plan": "plan",
    "ask": "ask",
}
```

`auto` 模式在用户界面中显示为 `bypass`，因为它使用了 `--dangerously-skip-permissions` 标志。

### display_mode(mode: str) -> str

将内部模式名转换为显示名称。

```python
display_mode("auto")  # → "bypass"
display_mode("code")  # → "code"
```

## 消息分割

### split_message(text, max_len=2000) -> list[str]

智能分割长文本为多个符合平台限制的消息块。

**分割策略优先级**（从高到低）：

1. **代码块边界** — 如果在代码块内部（奇数个 `` ``` ``），回退到最后一个完整代码块结束位置
2. **段落边界** — 在 `\n\n`（空行）处分割
3. **行边界** — 在 `\n` 处分割
4. **句子边界** — 在 `. `、`! `、`? `、`; ` 处分割
5. **空格** — 在空格处分割
6. **强制分割** — 在 `max_len` 位置强行切断

每种策略都有最小位置要求（通常为总长度的 30%~50%），避免分割出过短的块。

```python
# 使用示例
chunks = split_message(long_text, max_len=2000)   # Discord
chunks = split_message(long_text, max_len=4096)   # Telegram
```

### _find_split_point(text, max_len) -> int

内部函数，在 `text[:max_len]` 范围内找到最佳分割点。

**代码块检测**：
```python
code_blocks = list(re.finditer(r'```', segment))
if len(code_blocks) % 2 == 1:  # 奇数个 ```，说明在代码块内部
    last_block_start = code_blocks[-1].start()
    if last_block_start > 200:  # 至少保留 200 字符
        return last_block_start
```

## 格式化函数

### format_tool_use(event) -> str

格式化工具使用事件。

```python
# 有描述消息
"**[Tool: Write]** Writing file to disk"

# 有输入数据
"**[Tool: Bash]**\n```\nnpm install\n```"

# 仅工具名
"**[Tool: Read]**"
```

输入数据超过 500 字符时会被截断。

### format_session_info(session) -> str

格式化单个会话信息。支持两种数据源：

- **SessionRouter 的 Session 对象**：包含 `channel_id`、`machine_id`
  ```
  ● `a1b2c3d4...` gpu-1:/home/user/project [bypass] (active)
  ```

- **Daemon 返回的字典**：包含 `sessionId`、`path`
  ```
  ● `a1b2c3d4...` /home/user/project [bypass | claude-sonnet-4-20250514] (idle)
  ```

状态图标：
```python
status_icon = {
    "active": "●",
    "detached": "○",
    "destroyed": "✕",
    "idle": "●",
    "busy": "◉",
    "error": "✕",
}
```

### format_machine_list(machines) -> str

格式化机器列表。

```
Machines:
🟢 gpu-1 (gpu1.example.com) ⚡
  Paths: `/home/user/project-a`, `/home/user/project-b`
🔴 gpu-2 (gpu2.lab.internal) 💤
```

### format_session_list(sessions) -> str

格式化会话列表。

```
Sessions:
● `a1b2c3d4...` gpu-1:/home/user/project-a [bypass] (active)
○ `e5f67890...` gpu-1:/home/user/project-b [code] (detached)
```

### format_error(error) -> str

格式化错误消息。

```
**Error:** Connection timeout
```

### format_status(session, queue_stats) -> str

格式化 `/status` 命令输出。

```
Session Status
Machine: gpu-1
Path: /home/user/project
Mode: bypass
Status: active
Session ID: a1b2c3d4e5f6...
SDK Session: 789abcde0123...
Queue: 0 pending messages
Buffered: 0 responses
```

### format_health(machine_id, health) -> str

格式化 `/health` 命令输出。

```
Daemon Health - gpu-1
Status: OK
Uptime: 2h15m30s
Sessions: 3 (idle: 2, busy: 1)
Memory: 85MB RSS, 42/65MB heap
Node: v20.11.0 (PID: 12345)
```

运行时间会自动转换为可读格式（秒 → 分秒 → 时分秒）。

### format_monitor(machine_id, monitor) -> str

格式化 `/monitor` 命令输出。

```
Monitor - gpu-1 (uptime: 2h15m30s, 2 session(s))

● `a1b2c3d4...` idle [bypass | claude-sonnet-4-20250514]
  Path: /home/user/project-a
  Client: connected | Queue: 0 pending, 0 buffered

◉ `e5f67890...` busy [code | claude-sonnet-4-20250514]
  Path: /home/user/project-b
  Client: connected | Queue: 1 pending, 0 buffered
```

客户端断开时 "connected" 会显示为加粗的 "**disconnected**"。

## 与其他模块的关系

- **bot_base.py** — 调用所有格式化函数和 `split_message()`
- **bot_discord.py** — 调用 `split_message(max_len=2000)`、`format_error()`、`display_mode()`
- **bot_telegram.py** — 调用 `split_message(max_len=4096)`
