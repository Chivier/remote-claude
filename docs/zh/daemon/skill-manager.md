# 技能管理器（skill_manager.rs）

**文件：** `src/daemon/skill_manager.rs`

负责将说明文件和技能目录从共享源同步到远程机器上的项目目录。

## 用途

- 在会话创建时将共享说明/技能同步到项目目录
- 遵循“共享源 → 项目目录”的两阶段同步模型
- 避免覆盖已有的项目特定文件

## 架构

技能在系统中经历两个阶段的流转：

1. **Head Node -> 远程机器**：Head Node 上的 `ssh_manager.py` 通过 SCP 将本地 `~/.codecast/skills` 同步到远程机器的 `~/.codecast/skills`
2. **远程技能目录 -> 项目**：守护进程上的 `SkillManager` 在 `session.create` 时将远程共享目录中的文件复制到具体项目目录

## 关键方法

### `sync_to_project(project_path, cli_type) -> SyncResult`

同步时会先通过 `create_adapter(cli_type)` 确定：
- instruction file（如 `CLAUDE.md` / `AGENTS.md` / `GEMINI.md`）
- 是否需要同步 skills 目录（如 Claude 的 `.claude/skills/`）

具体行为：
1. 如果共享源目录不存在，返回空结果
2. 如果项目根目录中不存在目标 instruction file，则复制之
3. 如果目标 CLI 有 `skills_dir()`，则递归复制对应目录中不存在的文件
4. 所有已存在文件一律跳过，不覆盖

## 不覆盖原则

`SkillManager` 永远不会覆盖已有文件。这是有意为之的：
- 项目可能已经有自己的 `CLAUDE.md`
- 共享技能只是基线，项目自己的文件优先级更高
- 初次同步后，项目目录可以独立演化

## 当前 CLI 对应关系

| CLI | instruction file | skills dir |
|---|---|---|
| `claude` | `CLAUDE.md` | `.claude/skills/` |
| `codex` | `AGENTS.md` | 无 |
| `gemini` | `GEMINI.md` | 无 |
| `opencode` | `AGENTS.md` | 无 |

## 与其他模块的关系

- **src/head/ssh_manager.py** 负责把共享目录同步到远程 `~/.codecast/skills`
- **src/daemon/server.rs** 在 `session.create` 中调用 `sync_to_project()`
- **src/daemon/cli_adapter/mod.rs** 提供不同 CLI 的 instruction file / skills dir 定义

