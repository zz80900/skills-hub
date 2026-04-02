from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DbSession
from app.core.config import get_settings
from app.schemas.skill import SkillDetail, SkillListResponse, SkillSummary
from app.services.skill_service import get_skill_by_name, search_skills, to_skill_detail, to_skill_summary


router = APIRouter(prefix="/api", tags=["public"])


@router.get("/skills", response_model=SkillListResponse)
def list_skills(session: DbSession, q: str | None = Query(default=None, description="搜索关键词")):
    settings = get_settings()
    skills = [SkillSummary.model_validate(to_skill_summary(skill)) for skill in search_skills(session, q)]
    return SkillListResponse(items=skills, cli_install_command=settings.cli_install_command)


@router.get("/skills/{name}", response_model=SkillDetail)
def get_skill(name: str, session: DbSession):
    skill = get_skill_by_name(session, name)
    if skill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 不存在")
    return SkillDetail.model_validate(to_skill_detail(skill))

