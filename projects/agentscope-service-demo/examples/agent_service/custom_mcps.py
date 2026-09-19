"""Administrator-managed custom MCP library entries."""
import asyncio
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, Field
from fastapi import HTTPException, Request
from agentscope.mcp import MCPClient, HttpMCPConfig, StdioMCPConfig
from agentscope.app.storage import MCPRecord


class CustomMCPInput(BaseModel):
    name: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    description: str = Field(default='', max_length=2000)
    transport: Literal['http', 'stdio'] = 'http'
    url: str = Field(default='', max_length=4000)
    command: str = Field(default='', max_length=1000)
    args: list[str] = Field(default_factory=list, max_length=100)
    headers: dict[str, str] = Field(default_factory=dict)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    enabled: bool = True
    stateful: bool = True
    timeout: float = Field(default=20, ge=1, le=180)


def make_client(body):
    if body.transport == 'http':
        url = urlsplit(body.url)
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
            raise HTTPException(400, '请填写完整 HTTP(S) MCP 地址；认证信息放入 Headers')
        return MCPClient(name=body.name, is_stateful=body.stateful,
            mcp_config=HttpMCPConfig(url=body.url, headers=body.headers, timeout=body.timeout))
    if not body.command.strip() or any(c in body.command for c in ('\n', '\r', '\x00')):
        raise HTTPException(400, '请填写程序名或绝对路径，参数单独填写')
    if body.cwd and not body.cwd.startswith('/'):
        raise HTTPException(400, '工作目录必须是虚拟机内的绝对路径')
    return MCPClient(name=body.name, is_stateful=True, mcp_config=StdioMCPConfig(
        command=body.command, args=body.args, env=body.env, cwd=body.cwd or None))


def install_routes(router, app, require_admin):
    from portal import ADMIN

    @router.get('/custom-mcps')
    async def list_custom(request: Request):
        require_admin(request)
        return [{'id': r.id, 'name': r.name, 'description': r.description,
                 'enabled': r.enabled, 'client': r.client.model_dump(mode='json')}
                for r in await app.state.storage.list_mcps(ADMIN) if r.hub_id is None]

    async def save(body, request, mcp_id=None):
        require_admin(request)
        old = await app.state.storage.get_mcp(ADMIN, mcp_id) if mcp_id else None
        if mcp_id and (old is None or old.hub_id is not None):
            raise HTTPException(404, '自定义 MCP 不存在')
        client = make_client(body)
        if old and old.name != body.name:
            raise HTTPException(400, '修改配置时名称不可变；可新建其他名称的 MCP')
        record = MCPRecord(user_id=ADMIN, client=client, description=body.description,
            display_name=body.name, enabled=body.enabled, tags=['custom'])
        if old:
            record.id = old.id
        try:
            identifier = await app.state.storage.upsert_mcp(ADMIN, record)
        except ValueError:
            raise HTTPException(409, 'MCP 名称已存在，请换一个名称') from None
        return {'id': identifier, 'name': body.name}

    @router.post('/custom-mcps')
    async def create(body: CustomMCPInput, request: Request):
        return await save(body, request)

    @router.put('/custom-mcps/{mcp_id}')
    async def update(mcp_id: str, body: CustomMCPInput, request: Request):
        return await save(body, request, mcp_id)

    @router.post('/custom-mcps/{mcp_id}/test')
    async def test(mcp_id: str, request: Request):
        require_admin(request)
        record = await app.state.storage.get_mcp(ADMIN, mcp_id)
        if record is None or record.hub_id is not None:
            raise HTTPException(404, '自定义 MCP 不存在')
        client = MCPClient.model_validate(record.client.model_dump())
        try:
            # HttpMCPConfig has its own per-request timeout. Do not wrap the
            # MCP session in asyncio.timeout: cancellation can interrupt the
            # anyio transport's cleanup and turn an ordinary connection error
            # into an HTML 500 response through BaseHTTPMiddleware.
            await client.connect()
            tools = [tool.name for tool in await client.list_raw_tools()]
            return {'tools': tools}
        except Exception:
            raise HTTPException(400, '连接测试失败：请检查地址/认证、启动命令、依赖和服务器网络（25 秒超时）。') from None
        finally:
            if client.is_connected:
                await client.close()
