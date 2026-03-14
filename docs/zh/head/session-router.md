# 会话路由 (session_router.py)

`session_router.py` 使用 SQLite 数据库管理会话状态，将聊天频道映射到远程机器上的 Claude 会话。

**源文件**：`head/session_router.py`

## 职责

1. 持久化存储所有会话的状态（活跃、已分离、已销毁）
2. 将聊天频道（channel_id）映射到远程会话
3. 管理会话生命周期：创建 → 分离 → 恢复 → 销毁
4. 记录历史会话日志，支持会话恢复查询

## Session 数据类

```python
@dataclass
class Session:
    channel_id: str          # 聊天频道 ID (格式: "discord:123" 或 "telegram:456")
    machine_id: str          # 远程机器 ID
    path: str                # 远程项目路径
    daemon_session_id: str   # Daemon 侧的会话 ID (UUID)
    sdk_session_id: str|None # Claude SDK 会话 ID (用于 --resume)
    status: str              # active | detached | destroyed
    mode: str                # auto | code | plan | ask
    created_at: str          # 创建时间 (ISO 格式)
    updated_at: str          # 最后更新时间 (ISO 格式)
```

## 数据库结构

### sessions 表

主会话表。每个 `channel_id` 最多一条记录（PRIMARY KEY）。

```sql
CREATE TABLE sessions (
    channel_id TEXT PRIMARY KEY,
    machine_id TEXT NOT NULL,
    path TEXT NOT NULL,
    daemon_session_id TEXT NOT NULL,
    sdk_session_id TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    mode TEXT NOT NULL DEFAULT 'auto',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### session_log 表

历史会话日志。当会话被分离（detach）时，记录会写入此表。用于 `/resume` 命令查找历史会话。

```sql
CREATE TABLE session_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL,
    machine_id TEXT NOT NULL,
    path TEXT NOT NULL,
    daemon_session_id TEXT NOT NULL,
    sdk_session_id TEXT,
    mode TEXT,
    created_at TEXT NOT NULL,
    detached_at TEXT
);

CREATE INDEX idx_session_log_machine ON session_log(machine_id);
CREATE INDEX idx_session_log_daemon_id ON session_log(daemon_session_id);
```

## 关键方法

### resolve(channel_id) -> Optional[Session]

查找指定频道的**活跃**会话。

只返回 `status = 'active'` 的会话。这是最常用的方法——每次用户发送普通消息时都会调用，用于确定消息应该转发到哪个远程会话。

```python
session = router.resolve("discord:123456789")
if session:
    # 转发消息到 session.machine_id 上的 session.daemon_session_id
```

### register(channel_id, machine_id, path, daemon_session_id, mode)

注册一个新的活跃会话。

**行为**：
1. 如果该频道已有活跃会话，先将旧会话**自动分离**
2. 使用 `INSERT OR REPLACE` 插入新会话记录
3. 状态设为 `active`

这保证了每个频道在任何时刻最多只有一个活跃会话。

### update_sdk_session(channel_id, sdk_session_id)

更新活跃会话的 SDK 会话 ID。在 Claude 返回 `result` 事件时调用，将 Claude 的内部会话 ID 保存下来，用于后续的 `--resume` 恢复对话上下文。

### update_mode(channel_id, mode)

更新活跃会话的权限模式。在 `/mode` 命令执行后调用。

### detach(channel_id) -> Optional[Session]

分离活跃会话。

**行为**：
1. 将会话记录写入 `session_log`（包含 `detached_at` 时间戳）
2. 将 `sessions` 表中的 `status` 更新为 `detached`
3. 返回被分离的 Session 对象

内部使用 `_detach_internal` 方法在同一数据库连接中执行，支持事务。

### destroy(channel_id) -> Optional[Session]

标记会话为已销毁。将 `status` 更新为 `destroyed`。

> **注意**：`destroy` 只更新数据库状态，不会删除记录。实际终止 Daemon 侧的 Claude 进程需要通过 `DaemonClient.destroy_session()` 完成。

### list_sessions(machine_id: Optional[str]) -> list[Session]

列出所有会话，可选按机器 ID 过滤。按 `updated_at` 降序排列。

### list_active_sessions() -> list[Session]

仅列出活跃会话（`status = 'active'`）。

### find_session_by_daemon_id(daemon_session_id) -> Optional[Session]

通过 Daemon 会话 ID 查找会话。

**查找顺序**：
1. 先在 `sessions` 表中查找
2. 如果没找到，在 `session_log` 表中查找最近的记录

这个方法主要用于 `/resume` 命令，允许用户通过 Daemon 侧的会话 ID 恢复之前的会话。

### find_sessions_by_machine_path(machine_id, path) -> list[Session]

按机器 ID 和路径查找匹配的会话。用于 `/rm` 命令批量销毁会话。

## 会话生命周期

```
                 /start
                    │
                    ▼
              ┌──────────┐
              │  active   │ ← 每个频道最多一个活跃会话
              └────┬──────┘
                   │
          /exit    │    /start (同频道新会话)
                   │
                   ▼
              ┌──────────┐
              │ detached  │ ← 记录到 session_log
              └────┬──────┘
                   │
         /resume   │    /rm
          ┌────────┤
          │        │
          ▼        ▼
     ┌────────┐ ┌───────────┐
     │ active │ │ destroyed  │
     └────────┘ └───────────┘
```

## 线程安全

`SessionRouter` 在每次操作时创建新的 SQLite 连接并在操作完成后关闭。这意味着它天然支持多线程/多协程并发访问（SQLite 的文件锁机制处理并发写入）。

## 与其他模块的关系

- **bot_base.py** — 调用 `resolve()`、`register()`、`detach()`、`destroy()`、`list_sessions()` 等所有方法
- **main.py** — 实例化 `SessionRouter`，指定数据库路径
- **daemon_client.py** — SessionRouter 保存的 `daemon_session_id` 被传递给 DaemonClient 的各种方法
