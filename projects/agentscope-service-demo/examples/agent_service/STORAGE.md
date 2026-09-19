# 持久化存储

本部署统一使用 `/workspace/data/agentscope/`，不再依赖启动时的当前目录。
可通过绝对路径环境变量 `AGENTSCOPE_DATA_DIR` 覆盖；Python 服务与 Docker
Compose 必须使用同一个值。更换目录前需要停服务并迁移数据，不能直接指向空目录。

| 子目录 | 内容 |
| --- | --- |
| redis | Redis AOF 和 RDB：智能体、会话消息、模型凭证、资源登记、频道、日程、知识库元数据等 |
| portal/portal-data.json | 用户、角色、访问授权、项目、共享、站点 Logo、选择配置等 |
| projects | 项目共享文件及文件历史版本 |
| session-files | 普通会话独立文件 |
| skills | 上传技能包、解压内容及运行配置 |
| workspaces | 智能体工作区、Markdown 记忆及配置 |
| minio | MinIO 对象存储的数据卷：知识库上传原始文件及后续解析产物 |
| qdrant | 知识库向量索引（本地磁盘模式，只能由一个服务进程打开） |
| neo4j | GraphRAG 实体、关系及其文档分块来源 |
| backups | 可选备份目录；初次迁移备份已按用户要求清除，目前不自动生成备份 |
| logs | 可用于存放服务日志 |
| checks | 关机验证标记，不是项目或会话数据 |

## 启动

```bash
cd /workspace/projects/agentscope-service-demo/examples/agent_service
# 首次部署：cp .env.minio.example .env，并替换其中的密码。
docker compose -f compose.storage.yaml up -d
source ../../.venv/bin/activate
python main.py
```

Redis 容器 `agentscope-redis-demo` 使用固定宿主机目录、`unless-stopped`
自动重启策略，AOF 每秒刷盘，并保留 RDB 快照。不要再用原来的 `docker run --rm`。
Docker 服务需随系统启动；手动停止容器后需要再次 `up -d`。
MinIO 控制台只绑定本机 `127.0.0.1:9001`；需要查看时通过 SSH 隧道访问，
不要直接暴露到公网。Python 服务使用 `MINIO_ENDPOINT`、`MINIO_BUCKET`、
`MINIO_ACCESS_KEY` 和 `MINIO_SECRET_KEY` 连接对象存储。正式切换前先运行
`migrate_blobs_to_minio.py --dry-run`，确认后移除 `--dry-run`；它会保留旧本地
文件，直到确认知识库原文预览和重新索引正常。
Python 服务仍按上述方式启动，本次没有添加 Python 开机自启服务。

容器重建不删除宿主机数据。突然断电仍可能损失最近约一秒的 AOF 写入；
持久化不是备份，也不能防止磁盘损坏。定期停 Python 服务、停 Redis 后，
将整个数据目录备份到另一块磁盘/机器，再启动服务；复制时需要有权限读取 Redis 文件。
目录含凭证与聊天数据，应限制访问权限。

## 迁移说明

本平台已在迁移后按用户要求清空旧业务数据与迁移备份，重新初始化默认管理员。
下述迁移脚本只作历史记录，当前不要执行：
`migrate_storage.py` 仅用于这次 VM 的旧路径迁移：后端必须停止，目标目录必须不存在，
当前 Redis 必须为空。它校验文件副本，保留原件备份，并为旧目录留下兼容符号链接。
项目与会话文件的历史版本按新路径重新映射。不要重复执行迁移脚本。
未恢复昨天的 Redis；原先内存中的向量索引也不会凭空恢复，需要重新建立知识库索引。
旧文件虽然保留，但 Redis 中已丢失的资源登记和会话记录不会自动重建。

运行中的消息通知使用内存消息总线，不属于持久业务数据；重启不续跑正在执行的任务。
浏览器的当前会话选择等界面状态仍在浏览器本地，技能 Docker 镜像仍由 Docker 管理。

## 真实关机验证

关机前已使用 `check_persistence.py --initialize` 创建磁盘与 Redis 对照标记。
关机开机后进入本目录，运行（不要再次加 `--initialize`）：

```bash
../../.venv/bin/python check_persistence.py
```

输出 `PASS` 表示两处标记一致。然后启动 Python 服务，以 `wei` 登录，
检查关机前自行创建的项目、上传文件、智能体和会话是否仍在。
浏览器若保留旧会话 URL，回到首页重新选择；服务端已不保留旧业务数据。
`reset_platform_data.py --confirm-permanent-delete` 是破坏性清空工具，不是启动命令。
