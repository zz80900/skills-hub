from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.api.deps import DbSession, get_api_key_resource_user, get_optional_resource_user
from app.core.config import get_settings
from app.models.user import User
from app.schemas.collection import (
    CollectionManifestResponse,
    PublicCollectionDetail,
    PublicCollectionListResponse,
)
from app.schemas.local_library import PublicLocalLibraryResponse
from app.schemas.skill import (
    LocalSkillListResponse,
    PublicConfigResponse,
    PublicSkillDetail,
    RemoteSkillListResponse,
    SkillListResponse,
)
from app.services.resource_facade import (
    get_public_collection_detail,
    get_public_collection_manifest,
    get_public_skill_detail,
    list_local_library_items,
    list_local_skill_summaries,
    list_public_collections_response,
    list_remote_skill_summaries,
    resolve_collection_download,
    resolve_skill_download,
    search_skill_catalog,
)
from app.services.skill_service import PUBLIC_SOURCE_LOCAL
from app.services.skills_registry import get_remote_skill_detail, search_remote_skills
from app.services import nexus as nexus_service


router = APIRouter(prefix="/api", tags=["public"])


def _package_stream_response(package_url: str, filename: str) -> StreamingResponse:
    package_stream = nexus_service.open_package_stream(package_url)
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
    }
    if package_stream.content_length:
        headers["Content-Length"] = package_stream.content_length
    return StreamingResponse(
        package_stream.content,
        media_type="application/zip",
        headers=headers,
    )


@router.get("/public-config", response_model=PublicConfigResponse)
async def get_public_config():
    settings = get_settings()
    return PublicConfigResponse(cli_install_command=settings.cli_install_command)


@router.get("/local-library", response_model=PublicLocalLibraryResponse)
async def list_local_library(
    session: DbSession,
    current_user: User | None = Depends(get_optional_resource_user),
    q: str | None = Query(default=None, description="搜索关键词"),
):
    return PublicLocalLibraryResponse(items=list_local_library_items(session, q, current_user))


@router.get("/skills/local", response_model=LocalSkillListResponse)
async def list_local_skills(
    session: DbSession,
    current_user: User | None = Depends(get_optional_resource_user),
    q: str | None = Query(default=None, description="搜索关键词"),
):
    return LocalSkillListResponse(items=list_local_skill_summaries(session, q, current_user))


@router.get("/collections", response_model=PublicCollectionListResponse)
async def list_collections(
    session: DbSession,
    current_user: User | None = Depends(get_optional_resource_user),
    q: str | None = Query(default=None, description="搜索关键词"),
):
    return list_public_collections_response(session, current_user, q)


@router.get("/collections/{slug}/manifest", response_model=CollectionManifestResponse)
async def get_collection_manifest(
    slug: str,
    session: DbSession,
    current_user: User = Depends(get_api_key_resource_user),
    version: str | None = Query(default=None, description="Skill 集合版本"),
):
    return get_public_collection_manifest(
        session,
        current_user,
        slug=slug,
        version=version,
    )


@router.get("/collections/{slug}/package")
def download_collection_package(
    slug: str,
    session: DbSession,
    current_user: User = Depends(get_api_key_resource_user),
    version: str | None = Query(default=None, description="Skill 集合版本"),
):
    download = resolve_collection_download(session, current_user, slug=slug, version=version)
    return _package_stream_response(download.package_url, download.filename)


@router.get("/collections/{slug}", response_model=PublicCollectionDetail)
async def get_collection(
    slug: str,
    session: DbSession,
    current_user: User | None = Depends(get_optional_resource_user),
):
    return get_public_collection_detail(session, current_user, slug)


@router.get("/skills/skills_sh", response_model=RemoteSkillListResponse)
async def list_skills_sh_skills(
    q: str | None = Query(default=None, description="搜索关键词"),
    page: int = Query(default=1, ge=1, description="skills.sh 页码"),
    page_size: int = Query(default=12, ge=1, le=48, description="skills.sh 每页条数"),
):
    return await list_remote_skill_summaries(q, page, page_size, search_remote_skills)


@router.get("/skills", response_model=SkillListResponse)
async def list_skills(
    session: DbSession,
    current_user: User | None = Depends(get_optional_resource_user),
    q: str | None = Query(default=None, description="搜索关键词"),
    page: int = Query(default=1, ge=1, description="skills.sh 页码"),
    page_size: int = Query(default=12, ge=1, le=48, description="skills.sh 每页条数"),
    include_remote: bool = Query(default=True, description="是否同时查询 skills.sh"),
):
    return await search_skill_catalog(
        session,
        current_user,
        query=q,
        page=page,
        page_size=page_size,
        include_remote=include_remote,
        remote_search=search_remote_skills,
    )


@router.get("/skills/local/{slug}/versions/{version}", response_model=PublicSkillDetail)
async def get_local_skill_version(
    slug: str,
    version: str,
    session: DbSession,
    current_user: User | None = Depends(get_optional_resource_user),
):
    return await get_public_skill_detail(
        session,
        current_user,
        source=PUBLIC_SOURCE_LOCAL,
        slug=slug,
        version=version,
    )


@router.get("/skills/local/{slug}/package")
def download_local_skill_package(
    slug: str,
    session: DbSession,
    current_user: User = Depends(get_api_key_resource_user),
):
    download = resolve_skill_download(session, current_user, slug)
    return _package_stream_response(download.package_url, download.filename)


@router.get("/skills/{source}/{slug:path}", response_model=PublicSkillDetail)
async def get_skill(
    source: str,
    slug: str,
    session: DbSession,
    current_user: User | None = Depends(get_optional_resource_user),
):
    return await get_public_skill_detail(
        session,
        current_user,
        source=source,
        slug=slug,
        remote_detail_lookup=get_remote_skill_detail,
    )
