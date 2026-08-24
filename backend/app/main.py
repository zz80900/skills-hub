import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

import app.models
from app.api.auth import router as auth_router
from app.api.admin import router as admin_router
from app.api.public import router as public_router
from app.api.workspace import router as workspace_router
from app.core.config import get_settings
from app.core.rsa import initialize_key_manager, initialize_challenge_store
from app.db.base import Base
from app.db.schema import ensure_schema_compatibility
from app.db.session import engine
from app.mcp.server import mcp_exact_http_app, mcp_http_app, mcp_transport


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    initialize_key_manager(get_settings())
    initialize_challenge_store()
    Base.metadata.create_all(bind=engine)
    ensure_schema_compatibility(engine)
    if get_settings().mcp_enabled:
        async with mcp_transport.run():
            yield
    else:
        yield


class HealthCheckFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "/api/healthcheck" not in record.getMessage()


settings = get_settings()
app = FastAPI(title=settings.app_title, lifespan=lifespan)

OPENAPI_ROUTE_NAMES = frozenset(
    {
        "list_local_library",
        "list_local_skills",
        "list_collections",
        "get_collection_manifest",
        "download_collection_package",
        "get_collection",
        "list_skills_sh_skills",
        "list_skills",
        "get_local_skill_version",
        "download_local_skill_package",
        "get_skill",
        "list_workspace_skills",
        "create_workspace_skill",
        "get_workspace_skill",
        "update_workspace_skill",
        "delete_workspace_skill",
        "list_workspace_collections",
        "preview_workspace_collection_zip",
        "get_workspace_collection",
        "create_workspace_collection",
        "update_workspace_collection",
        "delete_workspace_collection",
    }
)


OPENAPI_SCOPE_TYPES = ["PUBLIC", "GROUP", "ORGANIZATION"]
OPENAPI_SKILL_SOURCES = ["local", "skills_sh"]
OPENAPI_VERSION_PATTERN = r"^[0-9]\.[0-9]\.[0-9]$"

OPENAPI_SCHEMA_DESCRIPTIONS = {
    "AdminSkillVersionSummary": "Skill 历史版本摘要。",
    "CollectionManifestItem": "Skill 集合清单中的单个条目。",
    "CollectionManifestResponse": "Skill 集合安装清单，供客户端解析和安装。",
    "CollectionPreviewItem": "Skill 集合预览中的单个 Skill 条目。",
    "CollectionPreviewResponse": "Skill 集合 ZIP 解包后的预览结果。",
    "CollectionSnapshotSummary": "Skill 集合历史版本摘要。",
    "HTTPValidationError": "请求参数校验失败时返回的错误结构。",
    "LocalSkillListResponse": "本地 Skill 列表响应。",
    "ManagedCollectionDetail": "工作区 Skill 集合详情。",
    "ManagedCollectionSummary": "工作区 Skill 集合摘要。",
    "ManagedSkillDetail": "工作区 Skill 详情。",
    "ManagedSkillSummary": "工作区 Skill 摘要。",
    "MessageResponse": "仅包含提示消息的通用响应。",
    "PublicCollectionDetail": "公开 Skill 集合详情。",
    "PublicCollectionListResponse": "公开 Skill 集合列表响应。",
    "PublicCollectionSummary": "公开 Skill 集合摘要。",
    "PublicLocalLibraryCollectionItem": "本地资源库中的 Skill 集合条目。",
    "PublicLocalLibraryResponse": "本地资源库中的 Skill 和集合混合列表响应。",
    "PublicLocalLibrarySkillItem": "本地资源库中的 Skill 条目。",
    "PublicSkillDetail": "公开 Skill 详情。",
    "PublicSkillSummary": "公开 Skill 摘要。",
    "RemoteSkillListResponse": "skills.sh Skill 列表响应。",
    "SkillListResponse": "本地 Skill 与 skills.sh 远程 Skill 的聚合列表响应。",
    "ValidationError": "单个请求参数校验错误。",
}

OPENAPI_SCHEMA_FIELD_DESCRIPTIONS = {
    "cli_install_command": "使用 CLI 安装资源时应执行的完整命令。",
    "contributor": "资源贡献者或最近发布者的用户名；可能为空。",
    "created_at": "资源创建时间，使用 ISO 8601 日期时间格式。",
    "ctx": "校验器提供的附加上下文信息；可能为空。",
    "current_version": "资源当前可用的版本号。",
    "deleted_at": "资源被软删除的时间；未删除时为空。",
    "description_html": "经过 Markdown 渲染后的 HTML 描述内容。",
    "description_markdown": "资源原始 Markdown 描述内容。",
    "detail": "参数校验错误明细列表。",
    "detail_url": "远程 Skill 的详情页地址；本地 Skill 可能为空。",
    "error": "远程查询失败时的可读错误信息；成功时为空。",
    "file_count": "条目包含的文件数量。",
    "group_id": "绑定的用户组 ID；未绑定用户组时为空。",
    "group_name": "绑定的用户组名称；未绑定用户组时为空。",
    "has_more": "是否还有下一页远程结果。",
    "history_versions": "资源历史版本号列表。",
    "id": "资源或关联对象的数字 ID。",
    "input": "触发校验失败的原始输入值；可能为空。",
    "install_command": "安装当前资源时应执行的完整命令。",
    "installs": "远程 Skill 的安装次数；本地 Skill 可能为空。",
    "is_deleted": "资源是否已被软删除。",
    "item_count": "集合中 Skill 条目的数量。",
    "items": "响应中的资源或清单条目列表。",
    "kind": "本地资源类型：`skill` 表示 Skill，`collection` 表示 Skill 集合。",
    "loc": "发生校验错误的位置，例如请求体、查询参数或具体字段名。",
    "local_items": "本地库中可见的 Skill 摘要列表。",
    "manifest": "Skill 集合的 manifest JSON 对象。",
    "message": "接口返回的提示消息。",
    "msg": "参数校验错误的可读消息。",
    "name": "资源显示名称。",
    "owner_username": "资源所有者用户名；可能为空。",
    "package_url": "可下载资源 ZIP 包的地址。",
    "page": "当前远程结果页码，从 1 开始。",
    "page_size": "当前远程结果每页条数。",
    "path": "ZIP 包内的相对路径。",
    "preview_items": "集合预览中的 Skill 条目列表。",
    "remote_error": "远程 skills.sh 查询失败时的可读错误信息；成功时为空。",
    "remote_has_more": "skills.sh 结果是否还有下一页。",
    "remote_items": "skills.sh 返回的 Skill 摘要列表。",
    "remote_page": "skills.sh 当前结果页码，从 1 开始。",
    "remote_page_size": "skills.sh 当前结果每页条数。",
    "schema_version": "集合安装清单的结构版本号。",
    "scope_label": "根据可见范围生成的中文展示名称。",
    "scope_org_level": "组织可见范围的层级，允许值为 1–4；非组织范围时为空。",
    "scope_org_name": "组织可见范围对应的组织节点名称；非组织范围时为空。",
    "scope_org_path": "组织可见范围对应的完整组织路径；非组织范围时为空。",
    "scope_type": "资源可见范围：`PUBLIC`=公开，`GROUP`=用户组成员可见，`ORGANIZATION`=组织范围可见。",
    "sha256": "文件内容的 SHA-256 校验值。",
    "slug": "资源唯一标识。",
    "source": "资源来源标识。",
    "source_label": "资源来源的中文展示名称。",
    "source_repository": "远程 Skill 的源代码仓库地址；本地 Skill 可能为空。",
    "type": "参数校验错误类型编码。",
    "updated_at": "资源最后更新时间，使用 ISO 8601 日期时间格式。",
    "version": "资源版本号。",
    "version_history": "资源历史版本摘要列表。",
    "zip_file": "上传的 ZIP 压缩包。",
}


def _set_schema_metadata(
    schema: dict[str, Any],
    *,
    description: str,
    example: Any | None = None,
    enum: list[Any] | None = None,
    pattern: str | None = None,
) -> None:
    schema["description"] = description
    if example is not None:
        schema["examples"] = [example]
    if enum is not None:
        schema["enum"] = enum
    if pattern is not None:
        schema["pattern"] = pattern


def _resolve_schema_reference(schema: dict[str, Any], openapi_schema: dict[str, Any]) -> dict[str, Any]:
    reference = schema.get("$ref")
    if not reference:
        return schema
    schema_name = reference.rsplit("/", 1)[-1]
    return openapi_schema.get("components", {}).get("schemas", {}).get(schema_name, schema)


def _schema_component_description(schema_name: str) -> str:
    if schema_name in OPENAPI_SCHEMA_DESCRIPTIONS:
        return OPENAPI_SCHEMA_DESCRIPTIONS[schema_name]
    if schema_name.startswith("Body_create_workspace_skill"):
        return "创建工作区 Skill 时使用的 multipart/form-data 字段。"
    if schema_name.startswith("Body_update_workspace_skill"):
        return "更新工作区 Skill 时使用的 multipart/form-data 字段。"
    if schema_name.startswith("Body_create_workspace_collection"):
        return "创建工作区 Skill 集合时使用的 multipart/form-data 字段。"
    if schema_name.startswith("Body_update_workspace_collection"):
        return "更新工作区 Skill 集合时使用的 multipart/form-data 字段。"
    if schema_name.startswith("Body_preview_workspace_collection"):
        return "预览工作区 Skill 集合 ZIP 时使用的 multipart/form-data 字段。"
    return "接口请求或响应的数据结构。"


def _schema_field_metadata(
    schema_name: str,
    field_name: str,
    field_schema: dict[str, Any],
) -> tuple[str, Any | None, list[Any] | None, str | None]:
    description = OPENAPI_SCHEMA_FIELD_DESCRIPTIONS.get(
        field_name,
        f"接口数据结构中的 `{field_name}` 字段。",
    )
    example: Any | None = None
    enum: list[Any] | None = None
    pattern: str | None = None

    if field_name == "source":
        if schema_name.endswith("CollectionItem") or schema_name.startswith("PublicCollection"):
            description = "资源来源固定为 `collection`，表示本地 Skill 集合。"
            example = "collection"
            enum = ["collection"]
        else:
            description = "Skill 来源：`local` 表示本地库，`skills_sh` 表示 skills.sh。"
            example = "local"
            enum = OPENAPI_SKILL_SOURCES
    elif field_name == "kind":
        if schema_name.endswith("CollectionItem"):
            example = "collection"
            enum = ["collection"]
        elif schema_name.endswith("SkillItem"):
            example = "skill"
            enum = ["skill"]
    elif field_name == "scope_type":
        description = (
            "资源可见范围：`PUBLIC`=公开；`GROUP`=用户组成员可见；"
            "`ORGANIZATION`=组织范围可见。"
        )
        example = "PUBLIC"
        enum = [*OPENAPI_SCOPE_TYPES, None] if _schema_allows_null(field_schema) else OPENAPI_SCOPE_TYPES
    elif field_name == "scope_org_level":
        example = 3
        enum = [1, 2, 3, 4, None] if _schema_allows_null(field_schema) else [1, 2, 3, 4]
    elif field_name == "slug":
        example = "pdf-tools"
    elif field_name == "sha256":
        example = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        pattern = r"^[a-fA-F0-9]{64}$"
    elif field_name == "version":
        example = "1.0.0"
        pattern = OPENAPI_VERSION_PATTERN
    elif field_name in {"page", "remote_page"}:
        example = 1
    elif field_name in {"page_size", "remote_page_size"}:
        example = 12
    elif field_name in {"item_count", "file_count", "installs"}:
        example = 0

    return description, example, enum, pattern


def _schema_allows_null(field_schema: dict[str, Any]) -> bool:
    return any(option.get("type") == "null" for option in field_schema.get("anyOf", []))


def _parameter_description(
    path: str,
    parameter: dict[str, Any],
) -> tuple[str, Any | None, list[Any] | None, str | None] | None:
    name = parameter.get("name")
    parameter_in = parameter.get("in")

    if name == "Authorization" and parameter_in == "header":
        if path in {
            "/api/collections/{slug}/manifest",
            "/api/collections/{slug}/package",
            "/api/skills/local/{slug}/package",
        }:
            return (
                "必填。只接受 `Bearer ns-...` 格式的 API Key；该接口不接受登录 JWT。",
                "Bearer ns-xxxxxxxx",
                None,
                None,
            )
        if path.startswith("/api/workspace/"):
            return (
                "必填。凭证格式为 `Bearer <JWT>` 或 `Bearer <API Key>`；用于访问当前账号可管理的 Skill/集合。",
                "Bearer ns-xxxxxxxx",
                None,
                None,
            )
        return (
            "可选。凭证格式为 `Bearer <JWT>` 或 `Bearer <API Key>`；不传时只能看到公开资源。",
            "Bearer ns-xxxxxxxx",
            None,
            None,
        )

    if name == "q" and parameter_in == "query":
        return (
            "可选搜索关键词。按当前接口支持的名称、slug 或描述进行匹配；不传则返回全部可见结果。",
            "design",
            None,
            None,
        )
    if name == "page" and parameter_in == "query":
        return "skills.sh 结果页码，从 1 开始。", 1, None, None
    if name == "page_size" and parameter_in == "query":
        return "skills.sh 每页返回条数，范围为 1–48。", 12, None, None
    if name == "include_remote" and parameter_in == "query":
        return "是否同时查询 skills.sh；`true` 返回本地库和远程结果，`false` 只返回本地库。", True, None, None
    if name == "version" and parameter_in == "query":
        return "可选 Skill 集合版本号；格式为 `主版本.次版本.修订号`，例如 `1.0.0`。不传时使用当前版本。", "1.0.0", None, OPENAPI_VERSION_PATTERN

    if parameter_in != "path":
        return None
    if name == "source":
        return "Skill 来源：`local` 表示本地库，`skills_sh` 表示 skills.sh。", "local", OPENAPI_SKILL_SOURCES, None
    if name == "version":
        return "Skill 版本号，格式为 `主版本.次版本.修订号`，例如 `1.0.0`。", "1.0.0", None, OPENAPI_VERSION_PATTERN
    if name == "name":
        return "Skill 名称，只允许小写字母、数字和中划线，例如 `pdf-tools`。", "pdf-tools", None, r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    if name == "slug" and path.startswith("/api/collections/"):
        return "Skill 集合标识，只允许小写字母、数字和中划线，例如 `design-tools`。", "design-tools", None, r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    if name == "slug" and path.startswith("/api/skills/local/"):
        return "本地 Skill 名称，只允许小写字母、数字和中划线，例如 `pdf-tools`。", "pdf-tools", None, r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    if name == "slug":
        return "Skill 标识。远程 Skill 使用 `组织/仓库/Skill` 路径，本地 Skill 使用 Skill 名称。", "vercel-labs/agent-skills/frontend-design", None, None
    return None


def _body_field_metadata(
    path: str,
    method: str,
    field_name: str,
) -> tuple[str, Any | None, list[Any] | None, str | None] | None:
    is_skill = "/skills" in path
    is_update = method == "put"

    if field_name == "name":
        if is_skill:
            return "Skill 名称，只允许小写字母、数字和中划线，例如 `pdf-tools`。", "pdf-tools", None, r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
        update_note = "更新时留空则保留现有名称；" if is_update else ""
        return f"Skill 集合显示名称，{update_note}最长 128 个字符。", "design-tools", None, None
    if field_name == "slug":
        return "Skill 集合唯一标识，只允许小写字母、数字和中划线，例如 `design-tools`。", "design-tools", None, r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    if field_name == "description_markdown":
        suffix = "更新时不传或传空字符串会清空现有描述。" if is_update else "不传时默认为空字符串。"
        return f"Markdown 格式的资源描述；{suffix}", "用于生成界面展示和搜索摘要。", None, None
    if field_name == "scope_type":
        update_note = "更新接口未传时也会按默认值 `PUBLIC` 处理。" if is_update else ""
        return (
            "资源可见范围：`PUBLIC`=公开；`GROUP`=用户组成员可见（需同时提供 `group_id`）；"
            "`ORGANIZATION`=组织范围可见（需同时提供 `scope_org_level`、`scope_org_name`、`scope_org_path`）。"
            f"规范值使用大写，默认值为 `PUBLIC`。{update_note}",
            "PUBLIC",
            OPENAPI_SCOPE_TYPES,
            None,
        )
    if field_name == "group_id":
        return "当 `scope_type=GROUP` 时填写用户组 ID；当前用户必须有权管理该组。留空表示不绑定用户组。", "12", None, r"^([1-9][0-9]*)?$"
    if field_name == "scope_org_level":
        return (
            "当 `scope_type=ORGANIZATION` 时填写组织层级，允许值为 1–4；必须与组织名称和完整路径一起提供。",
            "3",
            ["", "1", "2", "3", "4"],
            r"^([1-4])?$",
        )
    if field_name == "scope_org_name":
        return "当 `scope_type=ORGANIZATION` 时填写组织节点名称，例如 `研发部`。", "研发部", None, None
    if field_name == "scope_org_path":
        return "当 `scope_type=ORGANIZATION` 时填写组织完整路径，使用 ` / ` 分隔，例如 `总部 / 技术中心 / 研发部`。", "总部 / 技术中心 / 研发部", None, None
    if field_name == "zip_file":
        if path == "/api/workspace/collections/preview":
            return "必填 ZIP 压缩包；根目录只能包含 Skill 目录，每个 Skill 目录都必须包含非空 `SKILL.md`。", "collection.zip", None, None
        if is_skill:
            if is_update:
                return "可选 Skill ZIP 压缩包；提供后会生成新版本，不提供则保留当前压缩包。根目录必须包含非空 `SKILL.md`。", "skill.zip", None, None
            return "必填 Skill ZIP 压缩包；压缩包根目录必须包含非空 `SKILL.md`。", "skill.zip", None, None
        if is_update:
            return "可选 Skill 集合 ZIP 压缩包；提供后会生成新版本，不提供则保留当前压缩包。", "collection.zip", None, None
        return "必填 Skill 集合 ZIP 压缩包；根目录只能包含 Skill 目录，每个 Skill 目录都必须包含非空 `SKILL.md`。", "collection.zip", None, None
    return None


def _enrich_openapi_documentation(openapi_schema: dict[str, Any]) -> None:
    for path, path_item in openapi_schema.get("paths", {}).items():
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue

            for parameter in operation.get("parameters", []):
                metadata = _parameter_description(path, parameter)
                if metadata is None:
                    continue
                description, example, enum, pattern = metadata
                parameter["description"] = description
                if parameter.get("name") == "Authorization" and path.startswith("/api/workspace/"):
                    parameter["required"] = True
                schema = parameter.setdefault("schema", {})
                if example is not None:
                    schema["examples"] = [example]
                if enum is not None:
                    schema["enum"] = enum
                if pattern is not None:
                    schema["pattern"] = pattern
                if (
                    parameter.get("name") == "Authorization"
                    and path
                    in {
                        "/api/collections/{slug}/manifest",
                        "/api/collections/{slug}/package",
                        "/api/skills/local/{slug}/package",
                    }
                ):
                    parameter["required"] = True

            request_body = operation.get("requestBody")
            if not request_body:
                continue
            if path == "/api/workspace/collections/preview":
                request_body["description"] = "上传 ZIP 预览 Skill 集合中的文件清单，不会创建或修改资源。"
            elif path.startswith("/api/workspace/skills"):
                request_body["description"] = (
                    "使用 multipart/form-data 创建 Skill；必须上传符合约束的 ZIP 文件。"
                    if method == "post"
                    else "使用 multipart/form-data 更新 Skill；ZIP 文件可选，上传时会生成新版本。"
                )
            elif path.startswith("/api/workspace/collections"):
                request_body["description"] = (
                    "使用 multipart/form-data 创建 Skill 集合；必须上传符合约束的 ZIP 文件。"
                    if method == "post"
                    else "使用 multipart/form-data 更新 Skill 集合；ZIP 文件可选，上传时会生成新版本。"
                )

            for media_type in request_body.get("content", {}).values():
                body_schema = _resolve_schema_reference(media_type.get("schema", {}), openapi_schema)
                for field_name, field_schema in body_schema.get("properties", {}).items():
                    metadata = _body_field_metadata(path, method, field_name)
                    if metadata is None:
                        continue
                    description, example, enum, pattern = metadata
                    _set_schema_metadata(
                        field_schema,
                        description=description,
                        example=example,
                        enum=enum,
                        pattern=pattern,
                    )

    for schema_name, component_schema in openapi_schema.get("components", {}).get("schemas", {}).items():
        component_schema.setdefault("description", _schema_component_description(schema_name))
        for field_name, field_schema in component_schema.get("properties", {}).items():
            if field_schema.get("description"):
                continue
            description, example, enum, pattern = _schema_field_metadata(
                schema_name,
                field_name,
                field_schema,
            )
            _set_schema_metadata(
                field_schema,
                description=description,
                example=example,
                enum=enum,
                pattern=pattern,
            )


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version or "0.1.0",
        openapi_version=app.openapi_version,
        routes=[
            route
            for route in app.routes
            if isinstance(route, APIRoute) and route.name in OPENAPI_ROUTE_NAMES
        ],
    )
    _enrich_openapi_documentation(openapi_schema)
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi
logging.getLogger("uvicorn.access").addFilter(HealthCheckFilter())
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(public_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(workspace_router)
if settings.mcp_enabled:
    app.add_route("/mcp", mcp_exact_http_app, name="mcp-exact", include_in_schema=False)
    app.mount("/mcp", mcp_http_app, name="mcp")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/healthcheck")
def app_healthcheck() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ok", "database": "ok"}


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
frontend_index = frontend_dist / "index.html"
if frontend_dist.exists():
    assets_dir = frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")


def _frontend_response(full_path: str = ""):
    if full_path.startswith("api/") or full_path == "health":
        raise HTTPException(status_code=404, detail="Not Found")
    requested_file = (frontend_dist / full_path).resolve()
    try:
        requested_file.relative_to(frontend_dist.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Not Found") from exc
    if requested_file.is_file():
        return FileResponse(requested_file)
    if frontend_index.exists():
        return FileResponse(frontend_index)
    raise HTTPException(status_code=404, detail="Frontend build not found")


@app.get("/", include_in_schema=False)
def frontend_root():
    return _frontend_response()


@app.get("/{full_path:path}", include_in_schema=False)
def frontend_app(full_path: str):
    return _frontend_response(full_path)
