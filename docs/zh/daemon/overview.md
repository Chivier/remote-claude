# 守护进程概览

守护进程是 Codecast 的远程代理组件。它运行在每台远程机器（GPU 服务器、云虚拟机等）上，提供用于管理 CLI 会话的 JSON-RPC + SSE 接口。

## 技术栈

- **语言：** Rust（2021 edition）
- **异步运行时：** tokio
- **HTTP 服务器：** Axum
- **序列化：** serde / serde_json
- **进程管理：** tokio::process
- **UUID：** uuid
- **日志：** tracing

## 模块结构

```
src/daemon/
├── main.rs              # Axum 服务入口：端口绑定、优雅关闭
├── server.rs            # JSON-RPC 路由、SSE 流、AppState
├── session_pool.rs      # 会话注册表、每消息生成进程、CliAdapter 调度
├── message_queue.rs     # 每会话用户消息 + 响应缓冲
├── skill_manager.rs     # 从 ~/.codecast/skills 同步说明/技能到项目目录
├── types.rs             # StreamEvent、SessionStatus、PermissionMode、RPC 类型
├── cli_adapter/
│   ├── mod.rs           # CliAdapter trait、create_adapter() 工厂、CLI_TYPES
│   ├── claude.rs        # Claude CLI adapter
│   ├── codex.rs         # Codex adapter
│   ├── gemini.rs        # Gemini adapter
│   └── opencode.rs      # OpenCode adapter
├── auth.rs              # Token-based auth middleware
├── config.rs            # 守护进程配置加载
└── tls.rs               # TLS 证书生成/加载
```

## 架构

守护进程使用**每消息生成进程**架构，而不是维护长期运行的 CLI 进程：

1. `session.create` 注册会话元数据（路径、模式、CLI 类型），但**不**生成进程。
2. `session.send` 选择对应的 `CliAdapter`，并在单次消息交换期间生成一个 CLI 子进程。
3. 进程在产生输出后退出。SDK 会话 ID 从事件流中捕获。
4. 下一次 `session.send` 通过 `--resume <sdkSessionId>`（或其他 CLI 的等价机制）延续对话。

## 安全性

守护进程默认只绑定到 `127.0.0.1`。如果通过 SSH 隧道访问，则依赖 SSH 做认证与加密；如果直接暴露 HTTPS，则通过 Bearer token + TLS 保护。

## 生命周期

1. **启动**：Head Node 的 SSHManager 部署守护进程二进制，并在远程机器上启动它。
2. **运行**：守护进程在 `POST /rpc` 上接受 JSON-RPC 请求，并为 `session.send` 返回 SSE 流。
3. **关闭**：收到 SIGTERM/SIGINT 后，守护进程会清理会话、停止子进程并退出。

## 环境 / 配置

守护进程从 `~/.codecast/daemon.yaml` 读取配置；环境变量可以覆盖关键项：

| 配置项 | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `port` | `DAEMON_PORT` | `9100` | 监听端口 |
| `bind` | `DAEMON_BIND` | `127.0.0.1` | 绑定地址 |
| `tokens_file` | — | `~/.codecast/tokens.yaml` | token 存储路径 |
| `tls_cert` | — | `~/.codecast/tls-cert.pem` | TLS 证书路径 |
| `tls_key` | — | `~/.codecast/tls-key.pem` | TLS 私钥路径 |
