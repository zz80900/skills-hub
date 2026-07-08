import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import DbSession, get_optional_current_user
from app.core.config import get_settings
from app.models.user import User
from app.schemas.skill import (
    LocalSkillListResponse,
    PublicConfigResponse,
    PublicSkillDetail,
    PublicSkillSummary,
    RemoteSkillListResponse,
    SkillListResponse,
)
from app.services.skill_service import (
    PUBLIC_SOURCE_LOCAL,
    get_public_skill_by_name,
    get_skill_version,
    get_skill_versions,
    search_public_skills,
    to_public_skill_detail as to_local_public_skill_detail,
    to_public_skill_summary as to_local_public_skill_summary,
    to_public_skill_version_detail,
)
from app.services.skills_registry import (
    PUBLIC_SOURCE_SKILLS_SH,
    get_remote_skill_detail,
    search_remote_skills,
    to_public_skill_detail as to_remote_public_skill_detail,
    to_public_skill_summary as to_remote_public_skill_summary,
)


router = APIRouter(prefix="/api", tags=["public"])


def _list_local_skill_summaries(
    session: DbSession,
    query: str | None,
    current_user: User | None,
) -> list[PublicSkillSummary]:
    return [
        PublicSkillSummary.model_validate(to_local_public_skill_summary(skill))
        for skill in search_public_skills(session, query, current_user)
    ]


async def _list_remote_skill_summaries(
    query: str | None,
    page: int,
    page_size: int,
) -> RemoteSkillListResponse:
    remote_items: list[PublicSkillSummary] = []
    remote_error: str | None = None
    remote_has_more = False
    try:
        remote_results, remote_has_more = await search_remote_skills(query, page=page, page_size=page_size)
        remote_items = [
            PublicSkillSummary.model_validate(to_remote_public_skill_summary(skill))
            for skill in remote_results
        ]
    except Exception:
        remote_error = "skills.sh 数据暂时不可用，请稍后重试。"

    return RemoteSkillListResponse(
        items=remote_items,
        error=remote_error,
        page=page,
        page_size=page_size,
        has_more=remote_has_more,
    )


@router.get("/public-config", response_model=PublicConfigResponse)
async def get_public_config():
    settings = get_settings()
    return PublicConfigResponse(cli_install_command=settings.cli_install_command)


@router.get("/skills/local", response_model=LocalSkillListResponse)
async def list_local_skills(
    session: DbSession,
    current_user: User | None = Depends(get_optional_current_user),
    q: str | None = Query(default=None, description="搜索关键词"),
):
    return LocalSkillListResponse(items=_list_local_skill_summaries(session, q, current_user))


@router.get("/skills/skills_sh", response_model=RemoteSkillListResponse)
async def list_skills_sh_skills(
    q: str | None = Query(default=None, description="搜索关键词"),
    page: int = Query(default=1, ge=1, description="skills.sh 页码"),
    page_size: int = Query(default=12, ge=1, le=48, description="skills.sh 每页条数"),
):
    return await _list_remote_skill_summaries(q, page, page_size)


@router.get("/skills", response_model=SkillListResponse)
async def list_skills(
    session: DbSession,
    current_user: User | None = Depends(get_optional_current_user),
    q: str | None = Query(default=None, description="搜索关键词"),
    page: int = Query(default=1, ge=1, description="skills.sh 页码"),
    page_size: int = Query(default=12, ge=1, le=48, description="skills.sh 每页条数"),
    include_remote: bool = Query(default=True, description="是否同时查询 skills.sh"),
):
    settings = get_settings()
    local_items = _list_local_skill_summaries(session, q, current_user)

    remote_response = RemoteSkillListResponse(items=[], page=page, page_size=page_size)
    if include_remote:
        session.close()
        remote_response = await _list_remote_skill_summaries(q, page, page_size)

    return SkillListResponse(
        local_items=local_items,
        remote_items=remote_response.items,
        cli_install_command=settings.cli_install_command,
        remote_error=remote_response.error,
        remote_page=remote_response.page,
        remote_page_size=remote_response.page_size,
        remote_has_more=remote_response.has_more,
    )


@router.get("/skills/local/{slug}/versions/{version}", response_model=PublicSkillDetail)
async def get_local_skill_version(
    slug: str,
    version: str,
    session: DbSession,
    current_user: User | None = Depends(get_optional_current_user),
):
    skill = get_public_skill_by_name(session, slug, current_user)
    if skill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 不存在")

    skill_version = get_skill_version(session, skill, version)
    if skill_version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 版本不存在")

    versions = get_skill_versions(session, skill)
    return PublicSkillDetail.model_validate(to_public_skill_version_detail(skill, skill_version, versions))


@router.get("/skills/{source}/{slug:path}", response_model=PublicSkillDetail)
async def get_skill(
    source: str,
    slug: str,
    session: DbSession,
    current_user: User | None = Depends(get_optional_current_user),
):
    if source == PUBLIC_SOURCE_LOCAL:
        skill = get_public_skill_by_name(session, slug, current_user)
        if skill is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 不存在")
        versions = get_skill_versions(session, skill)
        return PublicSkillDetail.model_validate(to_local_public_skill_detail(skill, versions))

    if source == PUBLIC_SOURCE_SKILLS_SH:
        try:
            skill = await get_remote_skill_detail(slug)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == status.HTTP_404_NOT_FOUND:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 不存在") from exc
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="skills.sh 详情获取失败") from exc
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="skills.sh 详情获取失败") from exc
        return PublicSkillDetail.model_validate(to_remote_public_skill_detail(skill))

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未知 Skill 来源")
