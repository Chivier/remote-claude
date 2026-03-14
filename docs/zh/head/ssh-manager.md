# SSH 管理 (ssh_manager.py)

`ssh_manager.py` 管理与远程机器的 SSH 连接、端口转发隧道、Daemon 部署和技能文件同步。

**源文件**：`head/ssh_manager.py`

## 职责

1. 维护 SSH 连接池和端口转发隧道
2. 自动部署和启动远程 Daemon
3. 同步技能文件到远程项目目录
4. 提供机器列表和在线状态查询

## 核心类

### SSHTunnel

表示一个活跃的 SSH 隧道。

```python
class SSHTunnel:
    machine_id: str                       # 机器 ID
    local_port: int                       # 本地端口
    conn: asyncssh.SSHClientConnection    # SSH 连接对象
    listener: asyncssh.SSHListener        # 端口转发监听器
```

**属性和方法**：

| 成员 | 说明 |
|------|------|
| `alive` | 属性，检查 SSH 连接是否仍然存活 |
| `close()` | 关闭隧道（先关闭 listener，再关闭 connection） |

### SSHManager

SSH 管理器，管理所有远程机器的连接和隧道。

```python
class SSHManager:
    config: Config                          # 全局配置
    machines: dict[str, MachineConfig]      # 机器配置映射
    tunnels: dict[str, SSHTunnel]           # 活跃隧道映射
    _next_port: int                         # 下一个可用本地端口（从 19100 开始）
    _daemon_source: Path                    # 本地 Daemon 源代码路径
```

## 关键方法

### ensure_tunnel(machine_id: str) -> int

确保到指定机器的 SSH 隧道已建立。返回本地端口号。

**流程**：

1. 检查是否已有活跃隧道
   - 如果有且 `alive` 为 True，直接返回本地端口
   - 如果有但已断开，关闭旧隧道并重新创建
2. 分配新的本地端口（自增，从 19100 开始）
3. 建立 SSH 连接（`_connect_ssh`）
4. 创建端口转发：`localhost:local_port` → `127.0.0.1:daemon_port`
5. 确保远程 Daemon 正在运行（`_ensure_daemon`）
6. 缓存隧道对象到 `self.tunnels`

```python
local_port = await ssh_manager.ensure_tunnel("gpu-1")
# local_port = 19100
# 现在可以通过 http://127.0.0.1:19100/rpc 访问远程 Daemon
```

### _connect_ssh(machine: MachineConfig) -> asyncssh.SSHClientConnection

建立到指定机器的 SSH 连接。

**支持的认证方式**：
- SSH 密钥（`client_keys`）
- 密码（直接或通过 `file:` 从文件读取）
- ssh-agent（默认，不指定密钥和密码时）

**跳板机支持**：
如果机器配置了 `proxy_jump`，会先连接到跳板机，然后通过跳板机建立到目标机器的连接（使用 asyncssh 的 `tunnel` 参数）。

```python
# 连接流程
jump_conn = await asyncssh.connect(jump_host)  # 先连接跳板机
conn = await asyncssh.connect(target_host, tunnel=jump_conn)  # 通过跳板机连接
```

> **注意**：`known_hosts=None` 表示接受任何主机密钥。适用于单用户、可信网络环境。

### _resolve_password(machine: MachineConfig) -> Optional[str]

解析密码配置。支持两种格式：
- 直接字符串：`password: my-secret`
- 文件引用：`password: file:~/.ssh/password.txt`

文件引用会自动展开 `~`，读取文件内容并去除尾部空白。

### _ensure_daemon(machine_id, conn)

确保远程 Daemon 进程正在运行。

**流程**：

1. 使用 `pgrep -f 'node.*dist/server\.js'` 检查 Daemon 进程
2. 如果正在运行，直接返回
3. 检查 Daemon 代码是否已安装（`dist/server.js` 和 `node_modules` 存在）
4. 如果缺失且 `auto_deploy` 为 True，调用 `_deploy_daemon` 部署
5. 构建 PATH 环境变量（包含 node 的 bin 目录和 `~/.local/bin`）
6. 使用 `nohup` 启动 Daemon：
   ```bash
   cd install_dir && \
   DAEMON_PORT=9100 \
   PATH=/path/to/node/bin:~/.local/bin:$PATH \
   nohup node dist/server.js > daemon.log 2>&1 &
   ```
7. 轮询健康检查端点（最多 15 次，每次间隔 2 秒），等待 Daemon 就绪

> PATH 的构建很关键——它确保 Daemon 启动的子进程（包括 `claude` CLI）能找到正确的 Node.js 和 Claude 可执行文件。

### _deploy_daemon(machine_id, conn)

通过 SCP 将 Daemon 代码部署到远程机器。

**流程**：

1. 如果本地 `dist/` 目录不存在，先执行 `npm run build`
2. 在远程创建安装目录 (`mkdir -p`)
3. 上传文件：
   - `package.json`
   - `package-lock.json`
   - `dist/` 目录（递归）
4. 在远程执行 `npm install --production`

### sync_skills(machine_id, remote_path)

同步技能文件到远程项目目录。

**同步规则**：
- `CLAUDE.md` — 仅在远程不存在时复制（不覆盖）
- `.claude/skills/` — 递归复制，已存在的文件不覆盖

```python
await ssh_manager.sync_skills("gpu-1", "/home/user/my-project")
```

如果 `config.skills.sync_on_start` 为 False 或本地技能目录不存在，此方法直接返回。

### list_machines() -> list[dict]

列出所有配置的机器及其状态。

**行为**：
- 跳过纯跳板机（被用作 `proxy_jump` 且没有 `default_paths` 的机器）
- 对每台机器尝试 SSH 连接（15 秒超时）
- 检查 Daemon 进程是否运行
- 返回包含 `id`、`host`、`user`、`status`（online/offline）、`daemon`（running/stopped）、`default_paths` 的字典列表

### get_local_port(machine_id) -> Optional[int]

获取指定机器的本地隧道端口号，如果隧道不存在或已断开，返回 `None`。

### close_all()

关闭所有 SSH 隧道和连接。在系统关闭时调用。

## 端口分配策略

本地端口从 19100 开始自增分配：
- 第一台机器：19100
- 第二台机器：19101
- 依此类推

端口号仅在 Head Node 运行期间有效，不会持久化。

## 与其他模块的关系

- **config.py** — 读取 `Config` 和 `MachineConfig`
- **bot_base.py** — 调用 `ensure_tunnel()`、`sync_skills()`、`list_machines()`、`get_local_port()`
- **main.py** — 实例化 `SSHManager` 并在关闭时调用 `close_all()`
