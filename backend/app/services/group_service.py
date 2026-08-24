from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, insert, literal, or_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, aliased, selectinload

from app.models.collection import SkillCollection
from app.models.group import (
    GROUP_MEMBERSHIP_ACTIVE,
    GROUP_MEMBERSHIP_CANCELLED,
    GROUP_MEMBERSHIP_DECLINED,
    GROUP_MEMBERSHIP_PENDING,
    GROUP_MEMBERSHIP_REMOVED,
    Group,
    GroupMembership,
)
from app.models.skill import Skill
from app.models.user import User
from app.services.user_service import ROLE_ADMIN


UNSET = object()
MAX_GROUPS_PER_CREATOR = 20
MAX_ACTIVE_GROUP_MEMBERS = 100
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_group_name(name: str) -> str:
    normalized = (name or "").strip()
    if not normalized:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="组名不能为空")
    return normalized


def normalize_group_description(description: str | None) -> str | None:
    normalized = (description or "").strip()
    return normalized or None


def _group_loader_options():
    return (
        selectinload(Group.memberships).selectinload(GroupMembership.user),
        selectinload(Group.memberships).selectinload(GroupMembership.invited_by),
        selectinload(Group.leader),
        selectinload(Group.creator),
    )


def _group_order_by():
    return (Group.updated_at.desc(), Group.id.desc())


def active_group_membership_exists(group_id_column, user_id: int):
    return (
        select(GroupMembership.id)
        .where(
            GroupMembership.group_id == group_id_column,
            GroupMembership.user_id == user_id,
            GroupMembership.status == GROUP_MEMBERSHIP_ACTIVE,
        )
        .exists()
    )


def is_effective_group_member(group: Group, user_id: int) -> bool:
    if group.leader_user_id == user_id:
        return True
    return any(
        membership.user_id == user_id and membership.status == GROUP_MEMBERSHIP_ACTIVE
        for membership in group.memberships
    )


def get_group_by_id(session: Session, group_id: int) -> Group | None:
    statement = select(Group).where(Group.id == group_id).options(*_group_loader_options())
    return session.scalar(statement)


def list_groups(session: Session) -> list[Group]:
    statement = select(Group).options(*_group_loader_options()).order_by(*_group_order_by())
    return list(session.scalars(statement).unique())


def list_visible_groups_for_actor(session: Session, actor: User) -> list[Group]:
    statement = select(Group).options(*_group_loader_options())
    if actor.role.name != ROLE_ADMIN:
        statement = statement.where(
            or_(
                Group.leader_user_id == actor.id,
                active_group_membership_exists(Group.id, actor.id),
            )
        )
    statement = statement.order_by(*_group_order_by())
    return list(session.scalars(statement).unique())


def list_managed_groups_for_actor(session: Session, actor: User) -> list[Group]:
    statement = select(Group).options(*_group_loader_options())
    if actor.role.name != ROLE_ADMIN:
        statement = statement.where(Group.leader_user_id == actor.id)
    statement = statement.order_by(*_group_order_by())
    return list(session.scalars(statement).unique())


def list_group_options_for_actor(session: Session, actor: User) -> list[Group]:
    statement = select(Group).options(selectinload(Group.leader))
    if actor.role.name != ROLE_ADMIN:
        statement = statement.where(
            or_(
                Group.leader_user_id == actor.id,
                active_group_membership_exists(Group.id, actor.id),
            )
        )
    statement = statement.order_by(*_group_order_by())
    return list(session.scalars(statement).unique())


def list_group_member_candidates(session: Session) -> list[User]:
    statement = (
        select(User)
        .where(User.is_active.is_(True))
        .order_by(User.username.asc(), User.id.asc())
    )
    return list(session.scalars(statement))


def list_pending_invitations(session: Session, actor: User) -> list[GroupMembership]:
    statement = (
        select(GroupMembership)
        .where(
            GroupMembership.user_id == actor.id,
            GroupMembership.status == GROUP_MEMBERSHIP_PENDING,
        )
        .options(
            selectinload(GroupMembership.group).selectinload(Group.leader),
            selectinload(GroupMembership.invited_by),
            selectinload(GroupMembership.user),
        )
        .order_by(GroupMembership.invited_at.desc(), GroupMembership.id.desc())
    )
    return list(session.scalars(statement).unique())


def _get_user_or_404(session: Session, user_id: int) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return user


def _ensure_active_user(user: User) -> None:
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="用户已停用")


def _normalize_member_ids(user_ids: list[int]) -> list[int]:
    normalized: list[int] = []
    seen: set[int] = set()
    for user_id in user_ids:
        if user_id in seen:
            continue
        seen.add(user_id)
        normalized.append(user_id)
    return normalized


def _ensure_members_exist(session: Session, user_ids: list[int]) -> list[User]:
    if not user_ids:
        return []
    statement = select(User).where(User.id.in_(user_ids)).order_by(User.username.asc(), User.id.asc())
    users = list(session.scalars(statement))
    if len(users) != len(set(user_ids)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="存在不存在的组员用户")
    return users


def _get_membership(session: Session, group_id: int, user_id: int) -> GroupMembership | None:
    return session.scalar(
        select(GroupMembership).where(
            GroupMembership.group_id == group_id,
            GroupMembership.user_id == user_id,
        )
    )


def _active_member_count(session: Session, group_id: int) -> int:
    return int(
        session.scalar(
            select(func.count(GroupMembership.id)).where(
                GroupMembership.group_id == group_id,
                GroupMembership.status == GROUP_MEMBERSHIP_ACTIVE,
            )
        )
        or 0
    )


def _ensure_group_capacity(session: Session, group_id: int) -> None:
    if _active_member_count(session, group_id) >= MAX_ACTIVE_GROUP_MEMBERS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"组成员数量已达 {MAX_ACTIVE_GROUP_MEMBERS} 人上限",
        )


def _ensure_creator_quota(session: Session, creator_user_id: int) -> None:
    if session.get_bind().dialect.name == "sqlite":
        return
    session.execute(select(User.id).where(User.id == creator_user_id).with_for_update()).scalar_one()
    group_count = int(
        session.scalar(
            select(func.count(Group.id)).where(Group.created_by_user_id == creator_user_id)
        )
        or 0
    )
    if group_count >= MAX_GROUPS_PER_CREATOR:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"每个用户最多创建 {MAX_GROUPS_PER_CREATOR} 个组",
        )


def _ensure_leader_membership(session: Session, group: Group) -> None:
    membership = _get_membership(session, group.id, group.leader_user_id)
    if membership is None:
        session.add(
            GroupMembership(
                group_id=group.id,
                user_id=group.leader_user_id,
                status=GROUP_MEMBERSHIP_ACTIVE,
            )
        )
        session.flush()
        return
    if membership.status != GROUP_MEMBERSHIP_ACTIVE:
        membership.status = GROUP_MEMBERSHIP_ACTIVE
        membership.resolved_at = _utcnow()
        session.add(membership)
        session.flush()


def can_manage_group_members(actor: User, group: Group) -> bool:
    return actor.role.name == ROLE_ADMIN or group.leader_user_id == actor.id


def _ensure_can_manage_group(
    actor: User,
    group: Group,
    detail: str = "无权维护该用户组",
) -> None:
    if not can_manage_group_members(actor, group):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def create_group(
    session: Session,
    actor: User,
    *,
    name: str,
    description: str | None,
    leader_user_id: int | None = None,
) -> Group:
    _ensure_active_user(actor)
    requested_leader_id = leader_user_id or actor.id
    if actor.role.name != ROLE_ADMIN and requested_leader_id != actor.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="普通用户只能将自己设为组长")

    leader = _get_user_or_404(session, requested_leader_id)
    _ensure_active_user(leader)
    _ensure_creator_quota(session, actor.id)
    normalized_name = normalize_group_name(name)
    normalized_description = normalize_group_description(description)
    creator_group_count = (
        select(func.count(Group.id))
        .where(Group.created_by_user_id == actor.id)
        .scalar_subquery()
    )
    try:
        group_id = session.scalar(
            insert(Group)
            .from_select(
                ["name", "description", "created_by_user_id", "leader_user_id"],
                select(
                    literal(normalized_name),
                    literal(normalized_description),
                    literal(actor.id),
                    literal(leader.id),
                ).where(creator_group_count < MAX_GROUPS_PER_CREATOR),
            )
            .returning(Group.id)
        )
        if group_id is None:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"每个用户最多创建 {MAX_GROUPS_PER_CREATOR} 个组",
            )
        group = session.get(Group, group_id)
        if group is None:
            session.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="创建组失败，请重试")
        _ensure_leader_membership(session, group)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="组名已存在") from exc
    except OperationalError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="创建组发生并发冲突，请重试") from exc
    return get_group_by_id(session, group.id) or group


def _assign_group_leader(session: Session, group: Group, leader_user_id: int) -> None:
    leader = _get_user_or_404(session, leader_user_id)
    _ensure_active_user(leader)
    membership = _get_membership(session, group.id, leader.id)
    if membership is None or membership.status != GROUP_MEMBERSHIP_ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="新组长必须是已确认且有效的组员",
        )
    group.leader_user_id = leader.id
    session.add(group)


def update_group(
    session: Session,
    actor: User,
    group: Group,
    *,
    name: str | object = UNSET,
    description: str | None | object = UNSET,
    leader_user_id: int | object = UNSET,
) -> Group:
    _ensure_can_manage_group(actor, group)
    if name is not UNSET:
        if name is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="组名不能为空")
        group.name = normalize_group_name(str(name))
    if description is not UNSET:
        next_description = description if description is None or isinstance(description, str) else str(description)
        group.description = normalize_group_description(next_description)
    if leader_user_id is not UNSET:
        if leader_user_id is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="组长不能为空")
        _assign_group_leader(session, group, int(leader_user_id))

    session.add(group)
    try:
        session.flush()
        _ensure_leader_membership(session, group)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="组名已存在") from exc
    return get_group_by_id(session, group.id) or group


def transfer_group_leader(
    session: Session,
    group: Group,
    actor: User,
    leader_user_id: int,
) -> Group:
    _ensure_can_manage_group(actor, group)
    _assign_group_leader(session, group, leader_user_id)
    _ensure_leader_membership(session, group)
    session.commit()
    return get_group_by_id(session, group.id) or group


def delete_group(session: Session, actor: User, group: Group) -> None:
    _ensure_can_manage_group(actor, group)
    referenced_skill_id = session.scalar(select(Skill.id).where(Skill.group_id == group.id).limit(1))
    referenced_collection_id = session.scalar(
        select(SkillCollection.id).where(SkillCollection.group_id == group.id).limit(1)
    )
    if referenced_skill_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="当前组仍被 Skill 引用，不能删除",
        )
    if referenced_collection_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="当前组仍被 Skill 集合引用，不能删除",
        )

    session.delete(group)
    session.commit()


def _prepare_invitation(
    session: Session,
    group: Group,
    actor: User,
    user: User,
    *,
    reject_existing: bool,
) -> GroupMembership:
    if user.id == group.leader_user_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="组长已经是已确认成员")

    membership = _get_membership(session, group.id, user.id)
    if membership is not None and membership.status == GROUP_MEMBERSHIP_ACTIVE:
        if reject_existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该用户已是已确认成员")
        return membership
    if membership is not None and membership.status == GROUP_MEMBERSHIP_PENDING:
        if reject_existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该用户已有待确认邀请")
        return membership

    _ensure_active_user(user)
    _ensure_group_capacity(session, group.id)
    invited_at = _utcnow()
    if membership is None:
        membership = GroupMembership(
            group_id=group.id,
            user_id=user.id,
            status=GROUP_MEMBERSHIP_PENDING,
            invited_by_user_id=actor.id,
            invited_at=invited_at,
        )
    else:
        membership.status = GROUP_MEMBERSHIP_PENDING
        membership.invited_by_user_id = actor.id
        membership.invited_at = invited_at
        membership.resolved_at = None
    session.add(membership)
    return membership


def invite_group_member(session: Session, group: Group, actor: User, user_id: int) -> Group:
    _ensure_can_manage_group(actor, group, "无权维护该组成员")
    user = _get_user_or_404(session, user_id)
    _prepare_invitation(session, group, actor, user, reject_existing=True)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该用户已有组关系") from exc
    return get_group_by_id(session, group.id) or group


def add_group_member(session: Session, group: Group, actor: User, user_id: int) -> Group:
    return invite_group_member(session, group, actor, user_id)


def accept_group_invitation(session: Session, actor: User, membership_id: int) -> Group:
    _ensure_active_user(actor)
    membership = session.scalar(
        select(GroupMembership)
        .where(GroupMembership.id == membership_id)
        .options(selectinload(GroupMembership.group))
        .with_for_update()
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="邀请不存在")
    if membership.user_id != actor.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权处理该邀请")
    if membership.status != GROUP_MEMBERSHIP_PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="邀请已处理或已失效")

    group_id = membership.group_id
    session.execute(
        select(Group.id).where(Group.id == membership.group_id).with_for_update()
    ).scalar_one()
    _ensure_group_capacity(session, membership.group_id)
    counted_membership = aliased(GroupMembership)
    active_count = (
        select(func.count(counted_membership.id))
        .where(
            counted_membership.group_id == group_id,
            counted_membership.status == GROUP_MEMBERSHIP_ACTIVE,
        )
        .scalar_subquery()
    )
    try:
        result = session.execute(
            update(GroupMembership)
            .where(
                GroupMembership.id == membership.id,
                GroupMembership.status == GROUP_MEMBERSHIP_PENDING,
                active_count < MAX_ACTIVE_GROUP_MEMBERS,
            )
            .values(status=GROUP_MEMBERSHIP_ACTIVE, resolved_at=_utcnow())
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"组成员数量已达 {MAX_ACTIVE_GROUP_MEMBERS} 人上限或邀请已失效",
            )
        session.commit()
    except (IntegrityError, OperationalError) as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="接受邀请发生并发冲突，请重试") from exc
    group = get_group_by_id(session, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户组不存在")
    return group


def reject_group_invitation(session: Session, actor: User, membership_id: int) -> None:
    membership = session.scalar(
        select(GroupMembership).where(GroupMembership.id == membership_id).with_for_update()
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="邀请不存在")
    if membership.user_id != actor.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权处理该邀请")
    if membership.status != GROUP_MEMBERSHIP_PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="邀请已处理或已失效")
    membership.status = GROUP_MEMBERSHIP_DECLINED
    membership.resolved_at = _utcnow()
    session.add(membership)
    session.commit()


def cancel_group_invitation(
    session: Session,
    group: Group,
    actor: User,
    user_id: int,
) -> Group:
    _ensure_can_manage_group(actor, group, "无权维护该组成员")
    membership = _get_membership(session, group.id, user_id)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="邀请不存在")
    if membership.status != GROUP_MEMBERSHIP_PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="邀请已处理或已失效")
    membership.status = GROUP_MEMBERSHIP_CANCELLED
    membership.resolved_at = _utcnow()
    session.add(membership)
    session.commit()
    return get_group_by_id(session, group.id) or group


def remove_group_member(session: Session, group: Group, actor: User, user_id: int) -> Group:
    _ensure_can_manage_group(actor, group, "无权维护该组成员")
    if user_id == group.leader_user_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="组长不能被移除，请先更换组长")

    membership = _get_membership(session, group.id, user_id)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="组员不存在")
    if membership.status != GROUP_MEMBERSHIP_ACTIVE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该用户不是已确认组员")

    membership.status = GROUP_MEMBERSHIP_REMOVED
    membership.resolved_at = _utcnow()
    session.add(membership)
    session.commit()
    return get_group_by_id(session, group.id) or group


def replace_group_members(session: Session, group: Group, actor: User, user_ids: list[int]) -> Group:
    _ensure_can_manage_group(actor, group, "无权维护该组成员")
    normalized_user_ids = _normalize_member_ids(user_ids)
    if group.leader_user_id not in normalized_user_ids:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="组长必须保留在组成员中")

    users = _ensure_members_exist(session, normalized_user_ids)
    users_by_id = {user.id: user for user in users}
    existing_memberships = {membership.user_id: membership for membership in group.memberships}
    target_user_ids = set(normalized_user_ids)
    resolved_at = _utcnow()

    for user_id, membership in existing_memberships.items():
        if user_id == group.leader_user_id or user_id in target_user_ids:
            continue
        if membership.status == GROUP_MEMBERSHIP_ACTIVE:
            membership.status = GROUP_MEMBERSHIP_REMOVED
            membership.resolved_at = resolved_at
            session.add(membership)
        elif membership.status == GROUP_MEMBERSHIP_PENDING:
            membership.status = GROUP_MEMBERSHIP_CANCELLED
            membership.resolved_at = resolved_at
            session.add(membership)

    session.flush()
    for user_id in normalized_user_ids:
        if user_id == group.leader_user_id:
            continue
        _prepare_invitation(
            session,
            group,
            actor,
            users_by_id[user_id],
            reject_existing=False,
        )

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="组成员更新发生冲突") from exc
    return get_group_by_id(session, group.id) or group


def resolve_group_for_skill_binding(session: Session, actor: User, group_id: int | None) -> Group | None:
    if group_id is None:
        return None

    group = get_group_by_id(session, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户组不存在")
    if actor.role.name == ROLE_ADMIN or is_effective_group_member(group, actor.id):
        return group
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权将 Skill 绑定到该组")


def to_group_member_summary(
    user: User,
    membership_status: str = GROUP_MEMBERSHIP_ACTIVE,
) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role.name,
        "source": user.source,
        "is_active": user.is_active,
        "status": membership_status,
    }


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def to_group_invitation_summary(membership: GroupMembership) -> dict[str, Any]:
    group = membership.group
    return {
        "membership_id": membership.id,
        "group_id": group.id,
        "group_name": group.name,
        "leader_user_id": group.leader_user_id,
        "leader_username": group.leader.username,
        "user_id": membership.user_id,
        "username": membership.user.username,
        "display_name": membership.user.display_name,
        "invited_by_user_id": membership.invited_by_user_id,
        "invited_by_username": membership.invited_by.username if membership.invited_by is not None else None,
        "invited_at": _isoformat(membership.invited_at or membership.created_at),
        "status": membership.status,
    }


def to_group_summary(group: Group, actor: User | None = None) -> dict[str, Any]:
    active_memberships = [
        membership
        for membership in group.memberships
        if membership.status == GROUP_MEMBERSHIP_ACTIVE
    ]
    members = [
        to_group_member_summary(membership.user, membership.status)
        for membership in active_memberships
    ]
    if all(member["id"] != group.leader_user_id for member in members):
        members.append(to_group_member_summary(group.leader))
    members.sort(key=lambda item: (item["id"] != group.leader_user_id, item["username"]))

    can_view_pending = (
        actor is None
        or actor.role.name == ROLE_ADMIN
        or group.leader_user_id == actor.id
    )
    pending_invitations = []
    if can_view_pending:
        pending_invitations = [
            to_group_invitation_summary(membership)
            for membership in group.memberships
            if membership.status == GROUP_MEMBERSHIP_PENDING
        ]
        pending_invitations.sort(
            key=lambda item: (item["invited_at"] or "", item["membership_id"]),
            reverse=True,
        )

    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "leader_user_id": group.leader_user_id,
        "leader_username": group.leader.username,
        "leader_display_name": group.leader.display_name,
        "created_by_user_id": group.created_by_user_id,
        "member_count": len(members),
        "members": members,
        "pending_invitation_count": len(pending_invitations),
        "pending_invitations": pending_invitations,
    }


def to_group_option(group: Group) -> dict[str, Any]:
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "leader_user_id": group.leader_user_id,
        "leader_username": group.leader.username,
    }
