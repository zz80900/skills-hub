from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.api.deps import DbSession, get_current_user, get_resource_user
from app.models.user import User
from app.schemas.auth import MessageResponse
from app.schemas.collection import CollectionPreviewResponse, ManagedCollectionDetail, ManagedCollectionSummary
from app.schemas.group import (
    GroupCreateRequest,
    GroupInvitationSummary,
    GroupLeaderUpdateRequest,
    GroupMemberCreateRequest,
    GroupMemberSummary,
    GroupMembersUpdateRequest,
    GroupOption,
    GroupSummary,
    GroupUpdateRequest,
)
from app.schemas.skill import ManagedSkillDetail, ManagedSkillSummary, OrganizationScopeOption
from app.services.group_service import (
    UNSET,
    accept_group_invitation,
    add_group_member,
    cancel_group_invitation,
    can_manage_group_members,
    create_group,
    delete_group,
    get_group_by_id,
    list_group_member_candidates,
    list_group_options_for_actor,
    list_managed_groups_for_actor,
    list_pending_invitations,
    list_visible_groups_for_actor,
    reject_group_invitation,
    remove_group_member,
    replace_group_members,
    to_group_invitation_summary,
    to_group_member_summary,
    to_group_option,
    to_group_summary,
    transfer_group_leader,
    update_group,
)
from app.services.resource_facade import (
    create_managed_collection,
    create_managed_skill,
    delete_managed_collection,
    delete_managed_skill,
    get_managed_collection,
    get_managed_skill,
    list_managed_collections,
    list_managed_skills,
    preview_managed_collection,
    update_managed_collection,
    update_managed_skill,
)
from app.services.skill_service import list_organization_scope_options


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


def _parse_optional_positive_int(raw_value: str | None, field_name: str) -> int | None:
    normalized = (raw_value or "").strip()
    if not normalized:
        return None
    try:
        value = int(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{field_name} 必须是整数") from exc
    if value <= 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{field_name} 必须是正整数")
    return value


@router.get("/skills", response_model=list[ManagedSkillSummary])
def list_workspace_skills(
    session: DbSession,
    current_user: User = Depends(get_resource_user),
    q: str | None = None,
):
    return list_managed_skills(session, current_user, q)


@router.get("/groups", response_model=list[GroupSummary])
def list_workspace_groups(
    session: DbSession,
    current_user: User = Depends(get_current_user),
):
    return [
        GroupSummary.model_validate(to_group_summary(group, current_user))
        for group in list_visible_groups_for_actor(session, current_user)
    ]


@router.post("/groups", response_model=GroupSummary, status_code=status.HTTP_201_CREATED)
def create_workspace_group(
    payload: GroupCreateRequest,
    session: DbSession,
    current_user: User = Depends(get_current_user),
):
    group = create_group(
        session,
        current_user,
        name=payload.name,
        description=payload.description,
        leader_user_id=payload.leader_user_id,
    )
    return GroupSummary.model_validate(to_group_summary(group, current_user))


@router.put("/groups/{group_id}", response_model=GroupSummary)
def update_workspace_group(
    group_id: int,
    payload: GroupUpdateRequest,
    session: DbSession,
    current_user: User = Depends(get_current_user),
):
    group = get_group_by_id(session, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户组不存在")
    provided_fields = payload.model_fields_set
    group = update_group(
        session,
        current_user,
        group,
        name=payload.name if "name" in provided_fields else UNSET,
        description=payload.description if "description" in provided_fields else UNSET,
        leader_user_id=payload.leader_user_id if "leader_user_id" in provided_fields else UNSET,
    )
    return GroupSummary.model_validate(to_group_summary(group, current_user))


@router.delete("/groups/{group_id}", response_model=MessageResponse)
def delete_workspace_group(
    group_id: int,
    session: DbSession,
    current_user: User = Depends(get_current_user),
):
    group = get_group_by_id(session, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户组不存在")
    delete_group(session, current_user, group)
    return MessageResponse(message="用户组已删除")


@router.get("/groups/options", response_model=list[GroupOption])
def list_workspace_group_options(
    session: DbSession,
    current_user: User = Depends(get_current_user),
):
    return [
        GroupOption.model_validate(to_group_option(group))
        for group in list_group_options_for_actor(session, current_user)
    ]


@router.get("/group-invitations", response_model=list[GroupInvitationSummary])
def list_workspace_group_invitations(
    session: DbSession,
    current_user: User = Depends(get_current_user),
):
    return [
        GroupInvitationSummary.model_validate(to_group_invitation_summary(invitation))
        for invitation in list_pending_invitations(session, current_user)
    ]


@router.post("/group-invitations/{membership_id}/accept", response_model=GroupSummary)
def accept_workspace_group_invitation(
    membership_id: int,
    session: DbSession,
    current_user: User = Depends(get_current_user),
):
    group = accept_group_invitation(session, current_user, membership_id)
    return GroupSummary.model_validate(to_group_summary(group, current_user))


@router.post("/group-invitations/{membership_id}/reject", response_model=MessageResponse)
def reject_workspace_group_invitation(
    membership_id: int,
    session: DbSession,
    current_user: User = Depends(get_current_user),
):
    reject_group_invitation(session, current_user, membership_id)
    return MessageResponse(message="已拒绝用户组邀请")


@router.get("/organizations/options", response_model=list[OrganizationScopeOption])
def list_workspace_organization_options(
    session: DbSession,
    current_user: User = Depends(get_current_user),
):
    return [
        OrganizationScopeOption.model_validate(option)
        for option in list_organization_scope_options(session, current_user)
    ]


@router.get("/collections", response_model=list[ManagedCollectionSummary])
def list_workspace_collections(
    session: DbSession,
    current_user: User = Depends(get_resource_user),
    q: str | None = None,
):
    return list_managed_collections(session, current_user, q)


@router.post("/collections/preview", response_model=CollectionPreviewResponse)
async def preview_workspace_collection_zip(
    current_user: User = Depends(get_resource_user),
    zip_file: UploadFile = File(...),
):
    return preview_managed_collection(await zip_file.read(), zip_file.filename or "")


@router.get("/collections/{slug}", response_model=ManagedCollectionDetail)
def get_workspace_collection(slug: str, session: DbSession, current_user: User = Depends(get_resource_user)):
    return get_managed_collection(session, current_user, slug)


@router.post("/collections", response_model=ManagedCollectionDetail, status_code=status.HTTP_201_CREATED)
async def create_workspace_collection(
    session: DbSession,
    current_user: User = Depends(get_resource_user),
    name: str = Form(...),
    slug: str = Form(...),
    description_markdown: str = Form(""),
    scope_type: str = Form(default="PUBLIC"),
    group_id: str = Form(default=""),
    scope_org_level: str = Form(default=""),
    scope_org_name: str = Form(default=""),
    scope_org_path: str = Form(default=""),
    zip_file: UploadFile = File(...),
):
    return create_managed_collection(
        session,
        current_user,
        name=name,
        slug=slug,
        description_markdown=description_markdown,
        scope_type=scope_type,
        group_id=_parse_group_id(group_id),
        scope_org_level=_parse_optional_positive_int(scope_org_level, "scope_org_level"),
        scope_org_name=scope_org_name,
        scope_org_path=scope_org_path,
        package_content=await zip_file.read(),
        package_filename=zip_file.filename or "",
    )


@router.put("/collections/{slug}", response_model=ManagedCollectionDetail)
async def update_workspace_collection(
    slug: str,
    session: DbSession,
    current_user: User = Depends(get_resource_user),
    name: str = Form(default=""),
    description_markdown: str = Form(""),
    scope_type: str = Form(default="PUBLIC"),
    group_id: str = Form(default=""),
    scope_org_level: str = Form(default=""),
    scope_org_name: str = Form(default=""),
    scope_org_path: str = Form(default=""),
    zip_file: UploadFile | None = File(default=None),
):
    package_content: bytes | None = None
    package_filename: str | None = None
    if zip_file is not None and zip_file.filename:
        package_content = await zip_file.read()
        package_filename = zip_file.filename
    return update_managed_collection(
        session,
        current_user,
        slug=slug,
        name=name or None,
        description_markdown=description_markdown,
        scope_type=scope_type,
        group_id=_parse_group_id(group_id),
        scope_org_level=_parse_optional_positive_int(scope_org_level, "scope_org_level"),
        scope_org_name=scope_org_name,
        scope_org_path=scope_org_path,
        package_content=package_content,
        package_filename=package_filename,
    )


@router.delete("/collections/{slug}", response_model=MessageResponse)
def delete_workspace_collection(slug: str, session: DbSession, current_user: User = Depends(get_resource_user)):
    return delete_managed_collection(session, current_user, slug)


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


@router.put("/groups/{group_id}/leader", response_model=GroupSummary)
def transfer_workspace_group_leader(
    group_id: int,
    payload: GroupLeaderUpdateRequest,
    session: DbSession,
    current_user: User = Depends(get_current_user),
):
    group = get_group_by_id(session, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户组不存在")
    group = transfer_group_leader(
        session,
        group,
        current_user,
        payload.leader_user_id,
    )
    return GroupSummary.model_validate(to_group_summary(group, current_user))


@router.post("/groups/{group_id}/invitations/{user_id}/cancel", response_model=GroupSummary)
def cancel_workspace_group_invitation(
    group_id: int,
    user_id: int,
    session: DbSession,
    current_user: User = Depends(get_current_user),
):
    group = get_group_by_id(session, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户组不存在")
    group = cancel_group_invitation(session, group, current_user, user_id)
    return GroupSummary.model_validate(to_group_summary(group, current_user))


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
    return GroupSummary.model_validate(to_group_summary(group, current_user))


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
    return GroupSummary.model_validate(to_group_summary(group, current_user))


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
    return GroupSummary.model_validate(to_group_summary(group, current_user))


@router.get("/skills/{name}", response_model=ManagedSkillDetail)
def get_workspace_skill(name: str, session: DbSession, current_user: User = Depends(get_resource_user)):
    return get_managed_skill(session, current_user, name)


@router.post("/skills", response_model=ManagedSkillDetail, status_code=status.HTTP_201_CREATED)
async def create_workspace_skill(
    session: DbSession,
    current_user: User = Depends(get_resource_user),
    name: str = Form(...),
    description_markdown: str = Form(""),
    scope_type: str = Form(default="PUBLIC"),
    group_id: str = Form(default=""),
    scope_org_level: str = Form(default=""),
    scope_org_name: str = Form(default=""),
    scope_org_path: str = Form(default=""),
    zip_file: UploadFile = File(...),
):
    return create_managed_skill(
        session,
        current_user,
        name=name,
        description_markdown=description_markdown,
        scope_type=scope_type,
        group_id=_parse_group_id(group_id),
        scope_org_level=_parse_optional_positive_int(scope_org_level, "scope_org_level"),
        scope_org_name=scope_org_name,
        scope_org_path=scope_org_path,
        package_content=await zip_file.read(),
        package_filename=zip_file.filename or "",
    )


@router.put("/skills/{name}", response_model=ManagedSkillDetail)
async def update_workspace_skill(
    name: str,
    session: DbSession,
    current_user: User = Depends(get_resource_user),
    description_markdown: str = Form(""),
    scope_type: str = Form(default="PUBLIC"),
    group_id: str = Form(default=""),
    scope_org_level: str = Form(default=""),
    scope_org_name: str = Form(default=""),
    scope_org_path: str = Form(default=""),
    zip_file: UploadFile | None = File(default=None),
):
    package_content: bytes | None = None
    package_filename: str | None = None
    if zip_file is not None and zip_file.filename:
        package_content = await zip_file.read()
        package_filename = zip_file.filename
    return update_managed_skill(
        session,
        current_user,
        name=name,
        description_markdown=description_markdown,
        scope_type=scope_type,
        group_id=_parse_group_id(group_id),
        scope_org_level=_parse_optional_positive_int(scope_org_level, "scope_org_level"),
        scope_org_name=scope_org_name,
        scope_org_path=scope_org_path,
        package_content=package_content,
        package_filename=package_filename,
    )


@router.delete("/skills/{name}", response_model=MessageResponse)
def delete_workspace_skill(name: str, session: DbSession, current_user: User = Depends(get_resource_user)):
    return delete_managed_skill(session, current_user, name)
