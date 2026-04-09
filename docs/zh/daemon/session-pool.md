# 会话池（session_pool.rs）

**文件：** `src/daemon/session_pool.rs`

使用每消息生成进程架构管理 CLI 会话。每条用户消息都会通过对应的 `CliAdapter` 生成一个新的 CLI 进程，并通过 `--resume`（或其他 CLI 的等价机制）保持对话连续性。

## 用途

- 维护会话元数据注册表（路径、模式、CLI 类型、状态、SDK 会话 ID）
- 为单条消息生成 CLI 进程
- 将 CLI 的 stdout JSON 行转换为 `StreamEvent`
- 在 CLI 繁忙时处理消息排队
- 管理进程生命周期（生成、监控、中断、终止）
- 追踪客户端连接状态以进行响应缓冲

## 架构：每消息生成进程

SessionPool 不维护长期运行的 CLI 进程，而是为每条消息生成新进程：

```bash
claude -p "user message" \
       --output-format stream-json \
       --verbose \
       [--resume <sdkSessionId>] \
       [--dangerously-skip-permissions]
```

**为何采用每消息生成方式？**
- 每个进程只在一次消息交换期间存活
- `--resume` 标志通过引用前一次交互的 SDK 会话 ID 来维持对话上下文
- 每次交互都拥有干净的进程状态，便于恢复和诊断

## 内部类型

### InternalSession

用运行时状态扩展托管会话：

```rust
struct InternalSession {
    session_id: String,
    path: String,
    mode: PermissionMode,
    cli_type: String,
    status: SessionStatus,
    sdk_session_id: Option<String>,
    created_at: DateTime<Utc>,
    last_activity_at: DateTime<Utc>,
    process: Option<Child>,
    queue: MessageQueue,
    processing: bool,
    model: Option<String>,
}
```

## 关键方法

### `create(path, mode, model, cli_type) -> Result<String, String>`

创建新会话。这是**轻量级**操作——只注册会话元数据：

1. 解析路径（展开 `~`，并将裸项目名映射到 `~/Projects/<name>`）
2. 验证路径存在
3. 生成会话 UUID
4. 插入 `status = idle`、无进程、带新建 `MessageQueue` 的 `InternalSession`
5. 返回会话 ID

### `send(session_id, message) -> mpsc::Receiver<StreamEvent>`

向会话发送消息。返回一个产出流事件的接收器。

**如果会话繁忙：**
- 通过 `queue.enqueue_user()` 将消息入队
- 返回一个 `Queued { position }` 事件

**如果会话空闲：**
- 将状态切换为 `Busy`
- 生成后台任务执行 `run_cli_process()`
- 将流事件转发到接收器

### `run_cli_process(session_id, message)`

内部方法，负责生成 CLI 子进程并产出事件。

**命令构建：**

```rust
let adapter = create_adapter(&session.cli_type);
let command = if let Some(sdk_id) = &session.sdk_session_id {
    adapter.build_resume_command(message, mode, cwd, sdk_id, model)
} else {
    adapter.build_command(message, mode, cwd, model)
};
```

**进程生成：**

```rust
let mut child = command
    .current_dir(&session.path)
    .stdin(Stdio::null())
    .stdout(Stdio::piped())
    .stderr(Stdio::piped())
    .spawn()?;
```

stdin 设为 null，因为当前使用的是通过命令行参数传递提示词的非交互调用方式。

**输出处理：**
- 使用 `tokio::io::BufReader` 逐行读取 stdout
- 每行交给 `adapter.parse_output_line()` 解析为一个或多个 `StreamEvent`
- stderr 以 adapter 指定的日志级别写入日志

**会话 ID 提取：**
- 首行输出会调用 `adapter.extract_session_id()`
- 如果提取到 ID，则保存到 `session.sdk_session_id`

**收尾：**
1. 清空 `session.process`
2. 将 `processing` 设为 `false`
3. 将 `status` 设为 `Idle`
4. 非零退出码时发出 `Error` 事件
5. 若队列中仍有消息，则自动处理下一条

### `resume(session_id, sdk_session_id?)`

在每消息生成模式下，这个方法只更新 `sdk_session_id`，让下一次 `send()` 使用 resume 命令，并调用 `queue.on_client_reconnect()`。

### `destroy(session_id)`

1. 向运行中的 CLI 进程发送 SIGTERM
2. 最多等待 5 秒；必要时发送 SIGKILL
3. 将状态设为 `Destroyed`
4. 清空消息队列
5. 从池中移除会话

### `set_mode(session_id, mode)` / `set_model(session_id, model)`

更新会话模式或模型配置，在下一次 `send()` 时生效。

### `interrupt(session_id)`

1. 向运行中的 CLI 进程发送 SIGTERM
2. 清空消息队列
3. 返回是否真的中断了活跃任务

### `client_disconnect(session_id)` / `client_reconnect(session_id)`

代理 `MessageQueue` 的客户端连接状态管理，在 SSE 连接断开或重连时由 `server.rs` 调用。

## 与其他模块的关系

- **server.rs** 创建单一 `SessionPool` 实例，并在 RPC 处理器中调用其方法
- 使用 **MessageQueue** 进行每会话消息缓冲
- 从 **types.rs** 导入 `SessionStatus`、`PermissionMode`、`StreamEvent`、`SessionInfo` 等类型

