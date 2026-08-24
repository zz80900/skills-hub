from typing import Annotated

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from app.db.session import SessionLocal
from app.mcp.auth import get_optional_mcp_user, require_mcp_user
from app.mcp.constants import (
    TOOL_COLLECTION_CREATE,
    TOOL_COLLECTION_DELETE,
    TOOL_COLLECTION_DOWNLOAD,
    TOOL_COLLECTION_GET,
    TOOL_COLLECTION_MANIFEST_GET,
    TOOL_COLLECTION_PREVIEW,
    TOOL_COLLECTION_UPDATE,
    TOOL_COLLECTIONS_LIST,
    TOOL_MANAGED_COLLECTION_GET,
    TOOL_MANAGED_COLLECTIONS_LIST,
    TOOL_MANAGED_SKILL_GET,
    TOOL_MANAGED_SKILLS_LIST,
    TOOL_SKILL_CREATE,
    TOOL_SKILL_DELETE,
    TOOL_SKILL_DOWNLOAD,
    TOOL_SKILL_GET,
    TOOL_SKILL_UPDATE,
    TOOL_SKILLS_SEARCH,
)
from app.mcp.models import DownloadDescriptor
from app.mcp.results import McpResult, decode_package_base64, execute_tool
from app.services.resource_facade import (
    create_managed_collection,
    create_managed_skill,
    delete_managed_collection,
    delete_managed_skill,
    get_managed_collection,
    get_managed_skill,
    get_public_collection_detail,
    get_public_collection_manifest,
    get_public_skill_detail,
    list_managed_collections,
    list_managed_skills,
    list_public_collections_response,
    preview_managed_collection,
    resolve_collection_download,
    resolve_skill_download,
    search_skill_catalog,
    update_managed_collection,
    update_managed_skill,
)
from app.services.skill_service import PUBLIC_SOURCE_LOCAL


PositiveId = Annotated[int, Field(gt=0)]
PositivePage = Annotated[int, Field(ge=1)]
PageSize = Annotated[int, Field(ge=1, le=48)]

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)
MUTATING = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True)


async def mcp_skills_search(
    query: str | None = None,
    page: PositivePage = 1,
    page_size: PageSize = 12,
    include_remote: bool = True,
) -> McpResult:
    async def operation():
        with SessionLocal() as session:
            actor = get_optional_mcp_user(session)
            return await search_skill_catalog(
                session,
                actor,
                query=query,
                page=page,
                page_size=page_size,
                include_remote=include_remote,
            )

    return await execute_tool(operation, "Skill 搜索完成")


async def mcp_skill_get(
    slug: str,
    source: str = PUBLIC_SOURCE_LOCAL,
    version: str | None = None,
) -> McpResult:
    async def operation():
        with SessionLocal() as session:
            actor = get_optional_mcp_user(session)
            return await get_public_skill_detail(
                session,
                actor,
                source=source,
                slug=slug,
                version=version,
            )

    return await execute_tool(operation, "Skill 详情获取成功")


async def mcp_skill_download(slug: str) -> McpResult:
    def operation():
        with SessionLocal() as session:
            actor = get_optional_mcp_user(session)
            download = resolve_skill_download(session, actor, slug)
            return DownloadDescriptor(
                download_path=download.download_path,
                filename=download.filename,
                version=download.version,
                requires_api_key=download.requires_api_key,
            )

    return await execute_tool(operation, "Skill 下载信息获取成功")


async def mcp_collections_list(query: str | None = None) -> McpResult:
    def operation():
        with SessionLocal() as session:
            actor = get_optional_mcp_user(session)
            return list_public_collections_response(session, actor, query)

    return await execute_tool(operation, "Skill 集合列表获取成功")


async def mcp_collection_get(slug: str) -> McpResult:
    def operation():
        with SessionLocal() as session:
            actor = get_optional_mcp_user(session)
            return get_public_collection_detail(session, actor, slug)

    return await execute_tool(operation, "Skill 集合详情获取成功")


async def mcp_collection_manifest_get(slug: str, version: str | None = None) -> McpResult:
    def operation():
        with SessionLocal() as session:
            actor = get_optional_mcp_user(session)
            return get_public_collection_manifest(session, actor, slug=slug, version=version)

    return await execute_tool(operation, "Skill 集合清单获取成功")


async def mcp_collection_download(slug: str, version: str | None = None) -> McpResult:
    def operation():
        with SessionLocal() as session:
            actor = get_optional_mcp_user(session)
            download = resolve_collection_download(session, actor, slug=slug, version=version)
            return DownloadDescriptor(
                download_path=download.download_path,
                filename=download.filename,
                version=download.version,
                requires_api_key=download.requires_api_key,
            )

    return await execute_tool(operation, "Skill 集合下载信息获取成功")


async def mcp_managed_skills_list(query: str | None = None) -> McpResult:
    def operation():
        with SessionLocal() as session:
            actor = require_mcp_user(session)
            return list_managed_skills(session, actor, query)

    return await execute_tool(operation, "可管理 Skill 列表获取成功")


async def mcp_managed_skill_get(name: str) -> McpResult:
    def operation():
        with SessionLocal() as session:
            actor = require_mcp_user(session)
            return get_managed_skill(session, actor, name)

    return await execute_tool(operation, "可管理 Skill 详情获取成功")


async def mcp_skill_create(
    name: str,
    package_base64: str,
    description_markdown: str = "",
    scope_type: str = "PUBLIC",
    group_id: PositiveId | None = None,
    scope_org_level: PositiveId | None = None,
    scope_org_name: str | None = None,
    scope_org_path: str | None = None,
) -> McpResult:
    def operation():
        with SessionLocal() as session:
            actor = require_mcp_user(session)
            package_content = decode_package_base64(package_base64)
            return create_managed_skill(
                session,
                actor,
                name=name,
                description_markdown=description_markdown,
                scope_type=scope_type,
                group_id=group_id,
                scope_org_level=scope_org_level,
                scope_org_name=scope_org_name,
                scope_org_path=scope_org_path,
                package_content=package_content,
                package_filename="package.zip",
            )

    return await execute_tool(operation, "Skill 创建成功")


async def mcp_skill_update(
    name: str,
    package_base64: str | None = None,
    description_markdown: str = "",
    scope_type: str = "PUBLIC",
    group_id: PositiveId | None = None,
    scope_org_level: PositiveId | None = None,
    scope_org_name: str | None = None,
    scope_org_path: str | None = None,
) -> McpResult:
    def operation():
        with SessionLocal() as session:
            actor = require_mcp_user(session)
            package_content = None if package_base64 is None else decode_package_base64(package_base64)
            return update_managed_skill(
                session,
                actor,
                name=name,
                description_markdown=description_markdown,
                scope_type=scope_type,
                group_id=group_id,
                scope_org_level=scope_org_level,
                scope_org_name=scope_org_name,
                scope_org_path=scope_org_path,
                package_content=package_content,
                package_filename="package.zip" if package_content is not None else None,
            )

    return await execute_tool(operation, "Skill 更新成功")


async def mcp_skill_delete(name: str) -> McpResult:
    def operation():
        with SessionLocal() as session:
            actor = require_mcp_user(session)
            return delete_managed_skill(session, actor, name)

    return await execute_tool(operation, "Skill 删除成功")


async def mcp_managed_collections_list(query: str | None = None) -> McpResult:
    def operation():
        with SessionLocal() as session:
            actor = require_mcp_user(session)
            return list_managed_collections(session, actor, query)

    return await execute_tool(operation, "可管理 Skill 集合列表获取成功")


async def mcp_managed_collection_get(slug: str) -> McpResult:
    def operation():
        with SessionLocal() as session:
            actor = require_mcp_user(session)
            return get_managed_collection(session, actor, slug)

    return await execute_tool(operation, "可管理 Skill 集合详情获取成功")


async def mcp_collection_preview(package_base64: str) -> McpResult:
    def operation():
        with SessionLocal() as session:
            require_mcp_user(session)
            package_content = decode_package_base64(package_base64)
            return preview_managed_collection(package_content, "package.zip")

    return await execute_tool(operation, "Skill 集合压缩包预览成功")


async def mcp_collection_create(
    name: str,
    slug: str,
    package_base64: str,
    description_markdown: str = "",
    scope_type: str = "PUBLIC",
    group_id: PositiveId | None = None,
    scope_org_level: PositiveId | None = None,
    scope_org_name: str | None = None,
    scope_org_path: str | None = None,
) -> McpResult:
    def operation():
        with SessionLocal() as session:
            actor = require_mcp_user(session)
            package_content = decode_package_base64(package_base64)
            return create_managed_collection(
                session,
                actor,
                name=name,
                slug=slug,
                description_markdown=description_markdown,
                scope_type=scope_type,
                group_id=group_id,
                scope_org_level=scope_org_level,
                scope_org_name=scope_org_name,
                scope_org_path=scope_org_path,
                package_content=package_content,
                package_filename="package.zip",
            )

    return await execute_tool(operation, "Skill 集合创建成功")


async def mcp_collection_update(
    slug: str,
    package_base64: str | None = None,
    name: str | None = None,
    description_markdown: str = "",
    scope_type: str = "PUBLIC",
    group_id: PositiveId | None = None,
    scope_org_level: PositiveId | None = None,
    scope_org_name: str | None = None,
    scope_org_path: str | None = None,
) -> McpResult:
    def operation():
        with SessionLocal() as session:
            actor = require_mcp_user(session)
            package_content = None if package_base64 is None else decode_package_base64(package_base64)
            return update_managed_collection(
                session,
                actor,
                slug=slug,
                name=name,
                description_markdown=description_markdown,
                scope_type=scope_type,
                group_id=group_id,
                scope_org_level=scope_org_level,
                scope_org_name=scope_org_name,
                scope_org_path=scope_org_path,
                package_content=package_content,
                package_filename="package.zip" if package_content is not None else None,
            )

    return await execute_tool(operation, "Skill 集合更新成功")


async def mcp_collection_delete(slug: str) -> McpResult:
    def operation():
        with SessionLocal() as session:
            actor = require_mcp_user(session)
            return delete_managed_collection(session, actor, slug)

    return await execute_tool(operation, "Skill 集合删除成功")


def register_mcp_tools(server: MCPServer) -> None:
    tools = (
        (mcp_skills_search, TOOL_SKILLS_SEARCH, "搜索可见 Skill", READ_ONLY),
        (mcp_skill_get, TOOL_SKILL_GET, "获取可见 Skill 详情", READ_ONLY),
        (mcp_skill_download, TOOL_SKILL_DOWNLOAD, "获取 Skill 下载描述", READ_ONLY),
        (mcp_collections_list, TOOL_COLLECTIONS_LIST, "列出可见 Skill 集合", READ_ONLY),
        (mcp_collection_get, TOOL_COLLECTION_GET, "获取可见 Skill 集合详情", READ_ONLY),
        (mcp_collection_manifest_get, TOOL_COLLECTION_MANIFEST_GET, "获取 Skill 集合清单", READ_ONLY),
        (mcp_collection_download, TOOL_COLLECTION_DOWNLOAD, "获取 Skill 集合下载描述", READ_ONLY),
        (mcp_managed_skills_list, TOOL_MANAGED_SKILLS_LIST, "列出可管理 Skill", READ_ONLY),
        (mcp_managed_skill_get, TOOL_MANAGED_SKILL_GET, "获取可管理 Skill 详情", READ_ONLY),
        (mcp_skill_create, TOOL_SKILL_CREATE, "创建 Skill", MUTATING),
        (mcp_skill_update, TOOL_SKILL_UPDATE, "更新 Skill", MUTATING),
        (mcp_skill_delete, TOOL_SKILL_DELETE, "删除 Skill", DESTRUCTIVE),
        (
            mcp_managed_collections_list,
            TOOL_MANAGED_COLLECTIONS_LIST,
            "列出可管理 Skill 集合",
            READ_ONLY,
        ),
        (
            mcp_managed_collection_get,
            TOOL_MANAGED_COLLECTION_GET,
            "获取可管理 Skill 集合详情",
            READ_ONLY,
        ),
        (mcp_collection_preview, TOOL_COLLECTION_PREVIEW, "预览 Skill 集合压缩包", READ_ONLY),
        (mcp_collection_create, TOOL_COLLECTION_CREATE, "创建 Skill 集合", MUTATING),
        (mcp_collection_update, TOOL_COLLECTION_UPDATE, "更新 Skill 集合", MUTATING),
        (mcp_collection_delete, TOOL_COLLECTION_DELETE, "删除 Skill 集合", DESTRUCTIVE),
    )
    for function, name, description, annotations in tools:
        server.add_tool(
            function,
            name=name,
            description=description,
            annotations=annotations,
            structured_output=True,
        )
