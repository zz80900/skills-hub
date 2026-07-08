from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, get_current_user
from app.models.user import User
from app.schemas.auth import MessageResponse
from app.schemas.collection import CollectionPreviewResponse, ManagedCollectionDetail, ManagedCollectionSummary
from app.schemas.group import GroupMemberCreateRequest, GroupMemberSummary, GroupMembersUpdateRequest, GroupOption, GroupSummary
from app.schemas.skill import ManagedSkillDetail, ManagedSkillSummary, OrganizationScopeOption
from app.services.collection_service import (
    INITIAL_COLLECTION_VERSION,
    create_collection,
    get_collection_by_slug,
    get_collection_snapshots,
    get_next_collection_version,
    get_workspace_collection_by_slug,
    resolve_collection_scope,
    search_workspace_collections,
    soft_delete_collection,
    to_collection_detail,
    to_collection_summary,
    update_collection,
    validate_collection_name,
    validate_collection_slug,
    validate_collection_zip_file,
)
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
    list_organization_scope_options,
    resolve_skill_scope,
    search_workspace_skills,
    soft_delete_skill,
    to_admin_skill_detail,
    to_skill_summary,
    update_skill,
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
    current_user: User = Depends(get_current_user),
    q: str | None = None,
):
    return [
        ManagedCollectionSummary.model_validate(to_collection_summary(collection))
        for collection in search_workspace_collections(session, current_user, q)
    ]


@router.post("/collections/preview", response_model=CollectionPreviewResponse)
async def preview_workspace_collection_zip(
    current_user: User = Depends(get_current_user),
    zip_file: UploadFile = File(...),
):
    _, parsed_zip = await validate_collection_zip_file(zip_file)
    return CollectionPreviewResponse(
        version=INITIAL_COLLECTION_VERSION,
        item_count=len(parsed_zip.items),
        items=[item.__dict__ for item in parsed_zip.items],
    )


@router.get("/collections/{slug}", response_model=ManagedCollectionDetail)
def get_workspace_collection(slug: str, session: DbSession, current_user: User = Depends(get_current_user)):
    collection = get_workspace_collection_by_slug(session, validate_collection_slug(slug), current_user)
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 集合不存在")
    snapshots = get_collection_snapshots(session, collection)
    return ManagedCollectionDetail.model_validate(to_collection_detail(collection, snapshots))


@router.post("/collections", response_model=ManagedCollectionDetail, status_code=status.HTTP_201_CREATED)
async def create_workspace_collection(
    session: DbSession,
    current_user: User = Depends(get_current_user),
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
    validated_slug = validate_collection_slug(slug)
    validated_name = validate_collection_name(name)
    if get_collection_by_slug(session, validated_slug) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Skill 集合已存在")

    zip_content, parsed_zip = await validate_collection_zip_file(zip_file)
    resolved_scope_type, group, resolved_org_level, resolved_org_name, resolved_org_path = resolve_collection_scope(
        session,
        current_user,
        scope_type=scope_type,
        group_id=_parse_group_id(group_id),
        scope_org_level=_parse_optional_positive_int(scope_org_level, "scope_org_level"),
        scope_org_name=scope_org_name,
        scope_org_path=scope_org_path,
    )
    package_url = nexus_service.upload_collection_zip(validated_slug, INITIAL_COLLECTION_VERSION, zip_content)

    try:
        collection = create_collection(
            session,
            current_user,
            name=validated_name,
            slug=validated_slug,
            description_markdown=description_markdown,
            package_url=package_url,
            parsed_zip=parsed_zip,
            scope_type=resolved_scope_type,
            group=group,
            scope_org_level=resolved_org_level,
            scope_org_name=resolved_org_name,
            scope_org_path=resolved_org_path,
        )
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Skill 集合已存在") from exc
    snapshots = get_collection_snapshots(session, collection)
    return ManagedCollectionDetail.model_validate(to_collection_detail(collection, snapshots))


@router.put("/collections/{slug}", response_model=ManagedCollectionDetail)
async def update_workspace_collection(
    slug: str,
    session: DbSession,
    current_user: User = Depends(get_current_user),
    name: str = Form(default=""),
    description_markdown: str = Form(""),
    scope_type: str = Form(default="PUBLIC"),
    group_id: str = Form(default=""),
    scope_org_level: str = Form(default=""),
    scope_org_name: str = Form(default=""),
    scope_org_path: str = Form(default=""),
    zip_file: UploadFile | None = File(default=None),
):
    validated_slug = validate_collection_slug(slug)
    collection = get_workspace_collection_by_slug(session, validated_slug, current_user)
    if collection is None or collection.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 集合不存在")

    next_name = validate_collection_name(name or collection.name)
    package_url: str | None = None
    parsed_zip = None
    next_version: str | None = None
    if zip_file is not None and zip_file.filename:
        next_version = get_next_collection_version(collection.current_version)
        zip_content, parsed_zip = await validate_collection_zip_file(zip_file)
        package_url = nexus_service.upload_collection_zip(validated_slug, next_version, zip_content)

    resolved_scope_type, group, resolved_org_level, resolved_org_name, resolved_org_path = resolve_collection_scope(
        session,
        current_user,
        scope_type=scope_type,
        group_id=_parse_group_id(group_id),
        scope_org_level=_parse_optional_positive_int(scope_org_level, "scope_org_level"),
        scope_org_name=scope_org_name,
        scope_org_path=scope_org_path,
    )

    try:
        collection = update_collection(
            session,
            collection,
            name=next_name,
            description_markdown=description_markdown,
            package_url=package_url,
            parsed_zip=parsed_zip,
            version=next_version,
            scope_type=resolved_scope_type,
            group=group,
            scope_org_level=resolved_org_level,
            scope_org_name=resolved_org_name,
            scope_org_path=resolved_org_path,
        )
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Skill 集合版本已存在") from exc
    snapshots = get_collection_snapshots(session, collection)
    return ManagedCollectionDetail.model_validate(to_collection_detail(collection, snapshots))


@router.delete("/collections/{slug}", response_model=MessageResponse)
def delete_workspace_collection(slug: str, session: DbSession, current_user: User = Depends(get_current_user)):
    collection = get_workspace_collection_by_slug(session, validate_collection_slug(slug), current_user)
    if collection is None or collection.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 集合不存在")
    soft_delete_collection(session, collection)
    return MessageResponse(message="Skill 集合已删除")


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
    scope_type: str = Form(default="PUBLIC"),
    group_id: str = Form(default=""),
    scope_org_level: str = Form(default=""),
    scope_org_name: str = Form(default=""),
    scope_org_path: str = Form(default=""),
    zip_file: UploadFile = File(...),
):
    validated_name = validate_skill_name(name)
    if get_skill_by_name(session, validated_name) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Skill 已存在")

    zip_content = await validate_zip_file(zip_file)
    package_url = nexus_service.upload_skill_zip(validated_name, zip_content)
    resolved_scope_type, group, resolved_org_level, resolved_org_name, resolved_org_path = resolve_skill_scope(
        session,
        current_user,
        scope_type=scope_type,
        group_id=_parse_group_id(group_id),
        scope_org_level=_parse_optional_positive_int(scope_org_level, "scope_org_level"),
        scope_org_name=scope_org_name,
        scope_org_path=scope_org_path,
    )

    try:
        skill = create_skill(
            session,
            current_user,
            validated_name,
            description_markdown,
            package_url,
            scope_type=resolved_scope_type,
            group=group,
            scope_org_level=resolved_org_level,
            scope_org_name=resolved_org_name,
            scope_org_path=resolved_org_path,
        )
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
    scope_type: str = Form(default="PUBLIC"),
    group_id: str = Form(default=""),
    scope_org_level: str = Form(default=""),
    scope_org_name: str = Form(default=""),
    scope_org_path: str = Form(default=""),
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
    resolved_scope_type, group, resolved_org_level, resolved_org_name, resolved_org_path = resolve_skill_scope(
        session,
        current_user,
        scope_type=scope_type,
        group_id=_parse_group_id(group_id),
        scope_org_level=_parse_optional_positive_int(scope_org_level, "scope_org_level"),
        scope_org_name=scope_org_name,
        scope_org_path=scope_org_path,
    )

    skill = update_skill(
        session,
        skill,
        description_markdown,
        package_url,
        scope_type=resolved_scope_type,
        group=group,
        scope_org_level=resolved_org_level,
        scope_org_name=resolved_org_name,
        scope_org_path=resolved_org_path,
    )
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
