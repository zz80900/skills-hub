from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, get_current_admin
from app.core.config import get_settings
from app.core.security import create_access_token
from app.schemas.auth import LoginRequest, LoginResponse, MessageResponse
from app.schemas.skill import AdminSkillDetail, SkillSummary
from app.services import nexus as nexus_service
from app.services.skill_service import (
    create_skill,
    get_skill_by_name,
    search_skills,
    to_admin_skill_detail,
    to_skill_summary,
    update_skill,
    validate_skill_name,
    validate_zip_file,
)


router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest):
    settings = get_settings()
    if payload.username != settings.admin_username or payload.password != settings.admin_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    return LoginResponse(access_token=create_access_token(settings.admin_username))


@router.post("/logout", response_model=MessageResponse)
def logout(_: str = Depends(get_current_admin)):
    return MessageResponse(message="已退出登录")


@router.get("/skills", response_model=list[SkillSummary])
def list_admin_skills(session: DbSession, _: str = Depends(get_current_admin), q: str | None = None):
    return [SkillSummary.model_validate(to_skill_summary(skill)) for skill in search_skills(session, q)]


@router.get("/skills/{name}", response_model=AdminSkillDetail)
def get_admin_skill(name: str, session: DbSession, _: str = Depends(get_current_admin)):
    skill = get_skill_by_name(session, name)
    if skill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 不存在")
    return AdminSkillDetail.model_validate(to_admin_skill_detail(skill))


@router.post("/skills", response_model=AdminSkillDetail, status_code=status.HTTP_201_CREATED)
async def create_admin_skill(
    session: DbSession,
    _: str = Depends(get_current_admin),
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
        skill = create_skill(session, validated_name, description_markdown, package_url)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Skill 已存在") from exc
    return AdminSkillDetail.model_validate(to_admin_skill_detail(skill))


@router.put("/skills/{name}", response_model=AdminSkillDetail)
async def update_admin_skill(
    name: str,
    session: DbSession,
    _: str = Depends(get_current_admin),
    description_markdown: str = Form(""),
    zip_file: UploadFile | None = File(default=None),
):
    validated_name = validate_skill_name(name)
    skill = get_skill_by_name(session, validated_name)
    if skill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 不存在")

    package_url: str | None = None
    if zip_file is not None and zip_file.filename:
        zip_content = await validate_zip_file(zip_file)
        package_url = nexus_service.upload_skill_zip(validated_name, zip_content)

    skill = update_skill(session, skill, description_markdown, package_url)
    return AdminSkillDetail.model_validate(to_admin_skill_detail(skill))

