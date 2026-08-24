from contextlib import asynccontextmanager

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from app.core.config import get_settings
from app.mcp.auth import McpApiKeyAuthMiddleware
from app.mcp.constants import MCP_SERVER_NAME, MCP_SERVER_TITLE, MCP_SERVER_VERSION
from app.mcp.results import StructuredToolErrorMiddleware
from app.mcp.tools import register_mcp_tools


class McpExactPathAdapter:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        child_scope = dict(scope)
        child_scope["path"] = "/"
        child_scope["raw_path"] = b"/"
        await self.app(child_scope, receive, send)


class RestartableMcpTransport:
    def __init__(self, server: MCPServer) -> None:
        self.server = server
        self._app = None

    @asynccontextmanager
    async def run(self):
        runtime_settings = get_settings()
        streamable_http_app = self.server.streamable_http_app(
            streamable_http_path="/",
            json_response=True,
            stateless_http=True,
            max_request_body_size=runtime_settings.mcp_max_request_body_bytes,
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=runtime_settings.mcp_allowed_hosts,
                allowed_origins=runtime_settings.mcp_allowed_origins,
            ),
        )
        authenticated_app = McpApiKeyAuthMiddleware(streamable_http_app)
        self._app = authenticated_app
        try:
            async with self.server.session_manager.run():
                yield
        finally:
            if self._app is authenticated_app:
                self._app = None

    async def __call__(self, scope, receive, send) -> None:
        if self._app is None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8")],
                }
            )
            await send({"type": "http.response.body", "body": b"MCP transport is not running"})
            return
        await self._app(scope, receive, send)


mcp_server = MCPServer(
    name=MCP_SERVER_NAME,
    title=MCP_SERVER_TITLE,
    version=MCP_SERVER_VERSION,
    description="通过 MCP 浏览、下载和管理 NEXGO Skills 与 Skill 集合。",
    instructions=(
        "公开元数据工具可匿名调用；管理、预览和变更工具需要在 MCP HTTP 请求的 "
        "Authorization Bearer 中提供当前有效的 ns- API Key。下载工具仅返回应用下载路径。"
    ),
    middleware=[StructuredToolErrorMiddleware()],
)
register_mcp_tools(mcp_server)

mcp_transport = RestartableMcpTransport(mcp_server)
mcp_http_app = mcp_transport
mcp_exact_http_app = McpExactPathAdapter(mcp_http_app)
