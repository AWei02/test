# -*- coding: utf-8 -*-
"""The example script to start the agent service."""
import os
import sys
from pathlib import Path

import uvicorn
from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware

from agentscope.app import create_app, SubAgentTemplate
from agentscope.app.channel import (
    DingTalkChannel,
    DiscordChannel,
    FeishuChannel,
)
from agentscope.app.hub import ClawSkillHub, GitHubMCPHub
from agentscope.app.message_bus import InMemoryMessageBus
from agentscope.app.rag.knowledge_base_manager import CollectionPerKbManager
from agentscope.app.rag.blob_store import S3BlobStore
from agentscope.app.storage import RedisStorage
from agentscope.mcp import MCPClient, StdioMCPConfig, HttpMCPConfig
from agentscope.middleware import AgenticMemoryMiddleware, MiddlewareBase
from agentscope.permission import PermissionContext, PermissionMode
from agentscope.rag import ApproxTokenChunker, QdrantStore
from agentscope.workspace import WorkspaceBase
from portal import PortalPolicy, PortalWorkspaceManager, install_portal
from data_paths import WORKSPACES, QDRANT
from graph_rag import GraphRagStore
from document_parsing import MarkdownIngressParser
from execution_audit import AuditMiddleware, install_audit


def load_service_env() -> None:
    """Load this deployment's local compose environment without a dependency.

    Docker Compose reads ``.env`` on its own; the Python service is normally
    launched directly, so it needs the same values for its MinIO client.
    Explicit environment variables always win over the file.
    """
    path = Path(__file__).with_name(".env")
    if not path.is_file():
        return
    for raw in path.read_text("utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_service_env()


def minio_blob_store() -> S3BlobStore:
    """Build the S3-compatible store used for knowledge source files.

    MinIO intentionally sits behind AgentScope's generic S3 adapter.  This
    keeps every document URI portable (``s3://bucket/key``), and means a
    later move to managed object storage does not require a data-model or API
    change.  The bucket itself is created by the ``minio-init`` compose job
    before this service is started.
    """
    from botocore.config import Config

    endpoint = os.getenv("MINIO_ENDPOINT", "http://127.0.0.1:9000")
    return S3BlobStore(
        bucket=os.getenv("MINIO_BUCKET", "agentscope-knowledge"),
        endpoint_url=endpoint,
        aws_access_key_id=os.getenv("MINIO_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("MINIO_SECRET_KEY"),
        use_ssl=endpoint.startswith("https://"),
        # MinIO commonly runs behind one endpoint rather than virtual-hosted
        # buckets, so path-style addressing is the portable default.
        config=Config(s3={"addressing_style": "path"}),
    )

default_mcps = [
    MCPClient(
        name="browser-use",
        mcp_config=StdioMCPConfig(
            command="npx",
            args=["@playwright/mcp@latest"],
        ),
        is_stateful=True,
    ),
]

if os.getenv("AMAP_API_KEY"):
    default_mcps.append(
        MCPClient(
            name="amap",
            mcp_config=HttpMCPConfig(
                url=f"https://mcp.amap.com/mcp?key="
                f"{os.environ['AMAP_API_KEY']}",
            ),
            is_stateful=False,
        ),
    )

storage = RedisStorage(
    host=os.getenv("AGENTSCOPE_REDIS_HOST", "127.0.0.1"),
    port=int(os.getenv("AGENTSCOPE_REDIS_PORT", "6379")),
)

vector_store = QdrantStore(path=str(QDRANT))


async def longterm_memory_factory(
    user_id: str,
    agent_id: str,
    session_id: str,
    workspace: WorkspaceBase,
) -> list[MiddlewareBase]:
    """Attach Markdown-file long-term memory, stored under the session's
    workspace so it is reachable through whichever backend is bound."""
    del user_id, agent_id, session_id
    return [
        AuditMiddleware(),
        AgenticMemoryMiddleware(
            workdir=workspace.workdir,
            backend=workspace.get_backend(),
        ),
    ]


app = create_app(
    storage=storage,
    # Knowledge source files live in MinIO.  Metadata remains in Redis and
    # vectors in Qdrant; keeping these responsibilities separate makes every
    # layer independently recoverable and scalable.
    blob_store=minio_blob_store(),
    message_bus=InMemoryMessageBus(),
    # -- 如果要改用 Redis 作为消息总线（多进程/生产环境推荐）
    # -- 请取消下面代码的注释，并替换掉上面的 InMemoryMessageBus()：
    #
    # from agentscope.app.message_bus import RedisMessageBus
    # message_bus=RedisMessageBus(
    #     host="localhost",
    #     port=6379,
    # ),
    resource_access_policy=PortalPolicy(),
    workspace_manager=PortalWorkspaceManager(
        basedir=str(WORKSPACES),
        # 会被加载到工作区中的默认 MCP 服务
        default_mcps=default_mcps,
    ),
    # 知识库功能 —— 由磁盘版 Qdrant 向量库提供支持。
    # CollectionPerKbManager 会为每个知识库单独创建一个向量集合（collection），
    # 因此支持任意维度的向量嵌入（embedding）。
    knowledge_base_manager=CollectionPerKbManager(
        storage=storage,
        vector_store=vector_store,
    ),
    # 用户创建知识库时可选用的文本分块器类；
    # 选定的分块器类型和参数会固定绑定到该知识库上。
    knowledge_chunkers=[ApproxTokenChunker],
    knowledge_parsers=[MarkdownIngressParser()],
    # 在 /hub 页面供UI浏览的资源中心。资源中心本身不需要单独的凭证；
    # 每个 MCP 卡片会在它的 `inputs_schema` 里声明需要向用户索要的密钥。
    # 传入 ClawHub token 仅用于提升接口调用速率上限。
    mcp_hubs=[GitHubMCPHub()],
    skill_hubs=[ClawSkillHub(api_token=os.getenv("CLAWHUB_API_TOKEN"))],
    # 自定义子智能体模板
    custom_subagent_templates=[
        SubAgentTemplate(
            type="explorer",
            description=(
                "Read-only agents specialized in exploration tasks. It can "
                "read files but cannot modify, create, or delete them. Use "
                "this agent type when you need to investigate the codebase, "
                "understand its structure, or gather information from files "
                "to support planning—without making any changes."
            ),
            system_prompt_template="""You are {member_name}, an explorer \
agent in team '{team_name}' led by {leader_name}.

Team purpose: {team_description}

Your role: {member_description}

## Responsibilities
- Complete the exploration tasks assigned by the team leader.
- You are read-only: you may inspect files and the codebase, but you must \
never modify, create, or delete anything.

## Reporting
- Always report the task result back to {leader_name} using the TeamSay \
tool, whether the task succeeds or fails.
- Keep your private reasoning private; only share conclusions and findings \
that the leader needs.

Note: `TeamSay` is your ONLY channel to communicate with {leader_name} and \
the other team members. Any other output you produce is invisible to them, \
so anything you want them to see MUST be sent through `TeamSay`.""",
            permission_context=PermissionContext(
                # Read-only
                mode=PermissionMode.EXPLORE,
            ),
        ),
    ],
    # 长期记忆。默认采用 PER_AGENT（按智能体隔离）工作空间机制，
    # 可让记忆在同一个智能体的多次会话之间持续保留。
    extra_agent_middlewares=longterm_memory_factory,
    extra_middlewares=[
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        ),
    ],
    channels=[
        DingTalkChannel,
        DiscordChannel,
        FeishuChannel,
    ],
)

# GraphRAG is optional at boot: ordinary vector RAG keeps working if Neo4j is
# absent, while the portal surfaces a clear setup state instead of failing chat.
app.state.graph_rag_store = GraphRagStore.from_env()


install_audit(app)
install_portal(app)

from network_tools import install_web_search
install_web_search(app)

if __name__ == "__main__":
    # Start the service
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        # 在 Windows 系统下，热重载会强制使用 SelectorEventLoop，
        # 而该事件循环无法创建内置工具所依赖的子进程
        # Uploaded skills can contain .py files. They must not restart the
        # server, and chat SSE connections must not stall service shutdown.
        reload=os.getenv("PORTAL_DEV_RELOAD", "0") == "1" and sys.platform != "win32",
        timeout_graceful_shutdown=5,
    )
