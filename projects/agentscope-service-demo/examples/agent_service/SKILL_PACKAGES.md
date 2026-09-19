# 完整技能包

管理员：技能页面 → 上传完整技能包 → 选择 ZIP → 上传并安装依赖。
安装成功后进入原技能资源库，可在后台访问授权中分配给用户/角色。
普通用户必须在会话能力选择区勾选技能并应用，再让智能体执行。
管理员会话可直接使用已上传包；管理员原有主机工具权限保持不变。

## ZIP 约定

ZIP 根目录或单一顶层目录包含 SKILL.md，其 YAML 头部必须有 name、description。
name 为小写字母、数字及连字符，最多 64 字符；同名包拒绝覆盖。
保留完整 scripts、references、assets 等文件。
上限：压缩 20MB，解压 100MB，2000 个文件。拒绝路径穿越、链接、特殊文件、加密文件。

requirements.txt：在包专用 Docker 镜像构建时安装 Python 依赖。
runtime.json：可选，例如 {"apt_packages": ["ffmpeg"]}，安装 Debian 系统包。
安装阶段需要访问镜像仓库/PyPI/系统包源，可执行依赖构建代码，管理员应审核上传内容。
默认 Python 3.12 + Debian slim。上传的 Dockerfile 不作为构建指令。
暂不支持上传自己的镜像、任意基础镜像或交互式依赖安装。

## 执行

RunSkill(skill_id, path, action, args)：action=read 读取包内文本；action=run 运行 .py/.sh。
脚本可调用镜像内已安装的其他程序。stdin 非交互式，参数通过 args 数组传入。
运行结果包含退出码和最多 32KB 标准输出/错误输出。非零退出码视为工具失败。
容器路径 /skill 是只读技能根目录，/work 是当前用户/智能体/会话独立文件区。
聊天页技能文件区可上传输入和下载输出（根目录文件，单文件最多 20MB）。
不要使用聊天普通附件代替技能输入区；两者当前尚未自动关联。
脚本输出请保存至 /work 根目录。相对依赖文件可使用 /skill/assets 等路径。

普通用户每次调用再次校验技能选择、授权、存在性和启用状态。
撤销权限后旧工具对象也不能继续执行；已运行的调用不会被中途追溯撤销。
每次新建容器：无网络、只读镜像、非 root UID、移除 capabilities、no-new-privileges。
不挂载 Docker socket、宿主机项目目录、模型密钥或其他会话目录。
限制：512MB 内存、1 CPU、64 进程、60 秒执行、64MB 临时目录、单文件写入上限 64MB。
保留 /work 输出，容器执行完删除。用户授权不包含自动安装包的权限。

## 运维边界

本实现依赖宿主机 Docker 和 wei 的 Docker 权限。Docker 不是独立虚拟机，不用于恶意多租户生产托管。
目前仍采用用户名登录；需要上生产时增加真实认证、镜像审核、宿主机磁盘配额及清理策略。
skill-packages/ 保存技能文件及镜像引用；skill-workspaces/ 保存独立会话文件。
删除技能资源记录会阻止继续调用，但不自动删除镜像/包备份及历史输出，方便学习环境恢复。
脚本默认无网络；不能直接访问公网 API。需要联网能力可通过已授权 MCP 提供，或另行设计白名单网络。
这里只增强本地上传完整包；ClawHub 原来的安装/快照路径不自动转换为可执行包。

## 验证

python -m unittest test_skill_packages.py test_portal.py test_official_models.py
PORTAL_SKILL_TEST=1 python portal_smoke.py

后者用本地模拟模型验证真实 Agent 工具循环，不调用付费模型。
