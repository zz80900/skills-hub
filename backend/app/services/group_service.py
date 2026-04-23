from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models.group import Group, GroupMembership
from app.models.skill import Skill
from app.models.user import User
from app.services.user_service import ROLE_ADMIN


UNSET = object()


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
        selectinload(Group.leader),
    )


def _group_order_by():
    return (Group.updated_at.desc(), Group.id.desc())


def get_group_by_id(session: Session, group_id: int) -> Group | None:
    statement = (
        select(Group)
        .where(Group.id == group_id)
        .options(*_group_loader_options())
    )
    return session.scalar(statement)


def list_groups(session: Session) -> list[Group]:
    statement = select(Group).options(*_group_loader_options()).order_by(*_group_order_by())
    return list(session.scalars(statement))


def list_visible_groups_for_actor(session: Session, actor: User) -> list[Group]:
    statement = select(Group).options(*_group_loader_options())
    if actor.role.name != ROLE_ADMIN:
        membership_exists = (
            select(GroupMembership.id)
            .where(
                GroupMembership.group_id == Group.id,
                GroupMembership.user_id == actor.id,
            )
            .exists()
        )
        statement = statement.where(or_(Group.leader_user_id == actor.id, membership_exists))
    statement = statement.order_by(*_group_order_by())
    return list(session.scalars(statement).unique())


def list_managed_groups_for_actor(session: Session, actor: User) -> list[Group]:
    statement = select(Group).options(*_group_loader_options())
    if actor.role.name != ROLE_ADMIN:
        statement = statement.where(Group.leader_user_id == actor.id)
    statement = statement.order_by(*_group_order_by())
    return list(session.scalars(statement))


def list_group_options_for_actor(session: Session, actor: User) -> list[Group]:
    statement = select(Group).options(selectinload(Group.leader))
    if actor.role.name != ROLE_ADMIN:
        statement = (
            statement.join(GroupMembership, GroupMembership.group_id == Group.id)
            .where(GroupMembership.user_id == actor.id)
        )
    statement = statement.order_by(*_group_order_by())
    return list(session.scalars(statement).unique())


def list_group_member_candidates(session: Session) -> list[User]:
    statement = select(User).order_by(User.username.asc(), User.id.asc())
    return list(session.scalars(statement))


def _get_user_or_404(session: Session, user_id: int) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return user


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


def _ensure_leader_membership(session: Session, group: Group) -> None:
    statement = select(GroupMembership).where(
        GroupMembership.group_id == group.id,
        GroupMembership.user_id == group.leader_user_id,
    )
    membership = session.scalar(statement)
    if membership is None:
        session.add(GroupMembership(group_id=group.id, user_id=group.leader_user_id))
        session.flush()


def create_group(
    session: Session,
    *,
    name: str,
    description: str | None,
    leader_user_id: int,
) -> Group:
    leader = _get_user_or_404(session, leader_user_id)
    group = Group(
        name=normalize_group_name(name),
        description=normalize_group_description(description),
        leader_user_id=leader.id,
    )
    session.add(group)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="组名已存在") from exc

    _ensure_leader_membership(session, group)
    session.commit()
    return get_group_by_id(session, group.id) or group


def update_group(
    session: Session,
    group: Group,
    *,
    name: str | object = UNSET,
    description: str | None | object = UNSET,
    leader_user_id: int | object = UNSET,
) -> Group:
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
        leader = _get_user_or_404(session, int(leader_user_id))
        group.leader_user_id = leader.id

    session.add(group)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="组名已存在") from exc

    _ensure_leader_membership(session, group)
    session.commit()
    return get_group_by_id(session, group.id) or group


def delete_group(session: Session, group: Group) -> None:
    referenced_skill_id = session.scalar(select(Skill.id).where(Skill.group_id == group.id).limit(1))
    if referenced_skill_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="当前组仍被 Skill 引用，不能删除",
        )

    session.delete(group)
    session.commit()


def can_manage_group_members(actor: User, group: Group) -> bool:
    return actor.role.name == ROLE_ADMIN or group.leader_user_id == actor.id


def add_group_member(session: Session, group: Group, actor: User, user_id: int) -> Group:
    if not can_manage_group_members(actor, group):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权维护该组成员")

    user = _get_user_or_404(session, user_id)
    existing_membership = session.scalar(
        select(GroupMembership).where(
            GroupMembership.group_id == group.id,
            GroupMembership.user_id == user.id,
        )
    )
    if existing_membership is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该用户已在组内")

    session.add(GroupMembership(group_id=group.id, user_id=user.id))
    session.commit()
    return get_group_by_id(session, group.id) or group


def remove_group_member(session: Session, group: Group, actor: User, user_id: int) -> Group:
    if not can_manage_group_members(actor, group):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权维护该组成员")

    if user_id == group.leader_user_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="组长不能被移除，请先更换组长")

    membership = session.scalar(
        select(GroupMembership).where(
            GroupMembership.group_id == group.id,
            GroupMembership.user_id == user_id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="组员不存在")

    session.delete(membership)
    session.commit()
    return get_group_by_id(session, group.id) or group


def replace_group_members(session: Session, group: Group, actor: User, user_ids: list[int]) -> Group:
    if not can_manage_group_members(actor, group):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权维护该组成员")

    normalized_user_ids = _normalize_member_ids(user_ids)
    if group.leader_user_id not in normalized_user_ids:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="组长必须保留在组成员中")

    _ensure_members_exist(session, normalized_user_ids)

    existing_memberships = {membership.user_id: membership for membership in group.memberships}
    target_user_ids = set(normalized_user_ids)

    for user_id, membership in list(existing_memberships.items()):
        if user_id not in target_user_ids:
            session.delete(membership)

    for user_id in normalized_user_ids:
        if user_id not in existing_memberships:
            session.add(GroupMembership(group_id=group.id, user_id=user_id))

    session.commit()
    return get_group_by_id(session, group.id) or group


def resolve_group_for_skill_binding(session: Session, actor: User, group_id: int | None) -> Group | None:
    if group_id is None:
        return None

    group = get_group_by_id(session, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户组不存在")

    if actor.role.name == ROLE_ADMIN:
        return group

    member_ids = {membership.user_id for membership in group.memberships}
    if actor.id not in member_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权将 Skill 绑定到该组")
    return group


def to_group_member_summary(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role.name,
        "source": user.source,
        "is_active": user.is_active,
    }


def to_group_summary(group: Group) -> dict[str, Any]:
    members = [to_group_member_summary(membership.user) for membership in group.memberships]
    members.sort(key=lambda item: (item["id"] != group.leader_user_id, item["username"]))
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "leader_user_id": group.leader_user_id,
        "leader_username": group.leader.username,
        "leader_display_name": group.leader.display_name,
        "member_count": len(members),
        "members": members,
    }


def to_group_option(group: Group) -> dict[str, Any]:
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "leader_user_id": group.leader_user_id,
        "leader_username": group.leader.username,
    }
