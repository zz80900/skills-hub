from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, get_current_user
from app.models.user import User
from app.schemas.auth import MessageResponse
from app.schemas.group import GroupMemberCreateRequest, GroupMemberSummary, GroupMembersUpdateRequest, GroupOption, GroupSummary
from app.schemas.skill import ManagedSkillDetail, ManagedSkillSummary
from app.services.group_service import (
    add_group_member,
    can_manage_group_members,
    get_group_by_id,
    list_group_member_candidates,
    list_group_options_for_actor,
    list_managed_groups_for_actor,
    list_visible_groups_for_actor,
    remove_group_member,
    replace_group_members,
    to_group_member_summary,
    to_group_option,
    to_group_summary,
)
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
    resolve_skill_group,
    validate_skill_name,
    validate_zip_file,
)


router = APIRouter(prefix="/api/workspace", tags=["workspace"])


def _parse_group_id(raw_value: str | None) -> int | None:
    normalized = (raw_value or "").strip()
    if not normalized:
        return None
    try:
        group_id = int(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="group_id 必须是整数") from exc
    if group_id <= 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="group_id 必须是正整数")
    return group_id


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


@router.get("/groups", response_model=list[GroupSummary])
def list_workspace_groups(
    session: DbSession,
    current_user: User = Depends(get_current_user),
):
    return [
        GroupSummary.model_validate(to_group_summary(group))
        for group in list_visible_groups_for_actor(session, current_user)
    ]


@router.get("/groups/options", response_model=list[GroupOption])
def list_workspace_group_options(
    session: DbSession,
    current_user: User = Depends(get_current_user),
):
    return [
        GroupOption.model_validate(to_group_option(group))
        for group in list_group_options_for_actor(session, current_user)
    ]


@router.get("/groups/member-options", response_model=list[GroupMemberSummary])
def list_workspace_group_member_options(
    session: DbSession,
    current_user: User = Depends(get_current_user),
):
    if current_user.role.name != "ADMIN" and not list_managed_groups_for_actor(session, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前用户没有可管理的组")
    return [
        GroupMemberSummary.model_validate(to_group_member_summary(user))
        for user in list_group_member_candidates(session)
    ]


@router.put("/groups/{group_id}/members", response_model=GroupSummary)
def update_workspace_group_members(
    group_id: int,
    payload: GroupMembersUpdateRequest,
    session: DbSession,
    current_user: User = Depends(get_current_user),
):
    group = get_group_by_id(session, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户组不存在")
    if not can_manage_group_members(current_user, group):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权维护该组成员")
    group = replace_group_members(session, group, current_user, payload.user_ids)
    return GroupSummary.model_validate(to_group_summary(group))


@router.post("/groups/{group_id}/members", response_model=GroupSummary)
def create_workspace_group_member(
    group_id: int,
    payload: GroupMemberCreateRequest,
    session: DbSession,
    current_user: User = Depends(get_current_user),
):
    group = get_group_by_id(session, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户组不存在")
    group = add_group_member(session, group, current_user, payload.user_id)
    return GroupSummary.model_validate(to_group_summary(group))


@router.delete("/groups/{group_id}/members/{user_id}", response_model=GroupSummary)
def delete_workspace_group_member(
    group_id: int,
    user_id: int,
    session: DbSession,
    current_user: User = Depends(get_current_user),
):
    group = get_group_by_id(session, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户组不存在")
    group = remove_group_member(session, group, current_user, user_id)
    return GroupSummary.model_validate(to_group_summary(group))


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
    group_id: str = Form(default=""),
    zip_file: UploadFile = File(...),
):
    validated_name = validate_skill_name(name)
    if get_skill_by_name(session, validated_name) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Skill 已存在")

    zip_content = await validate_zip_file(zip_file)
    package_url = nexus_service.upload_skill_zip(validated_name, zip_content)
    group = resolve_skill_group(session, current_user, _parse_group_id(group_id))

    try:
        skill = create_skill(session, current_user, validated_name, description_markdown, package_url, group)
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
    group_id: str = Form(default=""),
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
    group = resolve_skill_group(session, current_user, _parse_group_id(group_id))

    skill = update_skill(session, skill, description_markdown, package_url, group)
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
