from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, get_current_user
from app.models.user import User
from app.schemas.auth import MessageResponse
from app.schemas.skill import ManagedSkillDetail, ManagedSkillSummary
from app.services import nexus as nexus_service
from app.services.skill_service import (
    create_skill,
    get_skill_by_name,
    get_skill_versions,
    get_workspace_skill_by_name,
    search_workspace_skills,
    soft_delete_skill,
    to_admin_skill_detail,
    to_skill_summary,
    update_skill,
    validate_skill_name,
    validate_zip_file,
)


router = APIRouter(prefix="/api/workspace", tags=["workspace"])


@router.get("/skills", response_model=list[ManagedSkillSummary])
def list_workspace_skills(
    session: DbSession,
    current_user: User = Depends(get_current_user),
    q: str | None = None,
):
    return [
        ManagedSkillSummary.model_validate(to_skill_summary(skill))
        for skill in search_workspace_skills(session, current_user, q)
    ]


@router.get("/skills/{name}", response_model=ManagedSkillDetail)
def get_workspace_skill(name: str, session: DbSession, current_user: User = Depends(get_current_user)):
    skill = get_workspace_skill_by_name(session, name, current_user)
    if skill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 不存在")
    versions = get_skill_versions(session, skill)
    return ManagedSkillDetail.model_validate(to_admin_skill_detail(skill, versions))


@router.post("/skills", response_model=ManagedSkillDetail, status_code=status.HTTP_201_CREATED)
async def create_workspace_skill(
    session: DbSession,
    current_user: User = Depends(get_current_user),
    name: str = Form(...),
    description_markdown: str = Form(""),
    zip_file: UploadFile = File(...),
):
    validated_name = validate_skill_name(name)
    if get_skill_by_name(session, validated_name) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Skill 已存在")

    zip_content = await validate_zip_file(zip_file)
    package_url = nexus_service.upload_skill_zip(validated_name, zip_content)

    try:
        skill = create_skill(session, current_user, validated_name, description_markdown, package_url)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Skill 已存在") from exc
    versions = get_skill_versions(session, skill)
    return ManagedSkillDetail.model_validate(to_admin_skill_detail(skill, versions))


@router.put("/skills/{name}", response_model=ManagedSkillDetail)
async def update_workspace_skill(
    name: str,
    session: DbSession,
    current_user: User = Depends(get_current_user),
    description_markdown: str = Form(""),
    zip_file: UploadFile | None = File(default=None),
):
    validated_name = validate_skill_name(name)
    skill = get_workspace_skill_by_name(session, validated_name, current_user)
    if skill is None or skill.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 不存在")

    package_url: str | None = None
    if zip_file is not None and zip_file.filename:
        zip_content = await validate_zip_file(zip_file)
        package_url = nexus_service.upload_skill_zip(validated_name, zip_content)

    skill = update_skill(session, skill, description_markdown, package_url)
    versions = get_skill_versions(session, skill)
    return ManagedSkillDetail.model_validate(to_admin_skill_detail(skill, versions))


@router.delete("/skills/{name}", response_model=MessageResponse)
def delete_workspace_skill(name: str, session: DbSession, current_user: User = Depends(get_current_user)):
    validated_name = validate_skill_name(name)
    skill = get_workspace_skill_by_name(session, validated_name, current_user)
    if skill is None or skill.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 不存在")
    soft_delete_skill(session, skill)
    return MessageResponse(message="Skill 已删除")
