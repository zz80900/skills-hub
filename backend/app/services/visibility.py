from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.group import GROUP_MEMBERSHIP_ACTIVE, Group, GroupMembership
from app.models.skill import SKILL_SCOPE_GROUP, SKILL_SCOPE_ORGANIZATION, SKILL_SCOPE_PUBLIC
from app.models.user import User
from app.services.group_service import resolve_group_for_skill_binding
from app.services.user_service import ROLE_ADMIN


SCOPE_OPTIONS = {SKILL_SCOPE_PUBLIC, SKILL_SCOPE_GROUP, SKILL_SCOPE_ORGANIZATION}


def normalize_optional_text(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized or None


def normalize_scope_type(scope_type: str | None) -> str:
    normalized = (scope_type or SKILL_SCOPE_PUBLIC).strip().upper()
    if normalized not in SCOPE_OPTIONS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="scope_type 非法")
    return normalized


def normalize_org_scope_payload(
    scope_org_level: int | None,
    scope_org_name: str | None,
    scope_org_path: str | None,
) -> tuple[int | None, str | None, str | None]:
    normalized_name = normalize_optional_text(scope_org_name)
    normalized_path = normalize_optional_text(scope_org_path)
    if scope_org_level is None and normalized_name is None and normalized_path is None:
        return None, None, None
    if scope_org_level is None or scope_org_level < 1 or scope_org_level > 4:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="scope_org_level 必须在 1 到 4 之间")
    if not normalized_name or not normalized_path:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="组织范围参数不完整")
    return int(scope_org_level), normalized_name, normalized_path


def actor_organization_levels(actor: User) -> list[str]:
    return [
        level
        for level in (actor.org_level_1, actor.org_level_2, actor.org_level_3, actor.org_level_4)
        if (level or "").strip()
    ]


def actor_organization_paths(actor: User) -> list[str]:
    levels = actor_organization_levels(actor)
    paths: list[str] = []
    for index in range(1, len(levels) + 1):
        paths.append(" / ".join(levels[:index]))
    return paths


def apply_public_visibility_filter(statement, model, actor: User | None):
    if actor is None:
        return statement.where(model.scope_type == SKILL_SCOPE_PUBLIC)
    if actor.role.name == ROLE_ADMIN:
        return statement

    membership_exists = (
        select(GroupMembership.id)
        .where(
            GroupMembership.group_id == model.group_id,
            GroupMembership.user_id == actor.id,
            GroupMembership.status == GROUP_MEMBERSHIP_ACTIVE,
        )
        .exists()
    )
    leader_exists = (
        select(Group.id)
        .where(
            Group.id == model.group_id,
            Group.leader_user_id == actor.id,
        )
        .exists()
    )
    org_paths = actor_organization_paths(actor)
    visibility_conditions = [model.scope_type == SKILL_SCOPE_PUBLIC]
    visibility_conditions.append(
        (model.scope_type == SKILL_SCOPE_GROUP) & or_(leader_exists, membership_exists)
    )
    for path in org_paths:
        visibility_conditions.append(
            (model.scope_type == SKILL_SCOPE_ORGANIZATION)
            & (model.scope_org_path == path)
        )
    return statement.where(or_(*visibility_conditions))


def build_scope_label(resource) -> str:
    if resource.scope_type == SKILL_SCOPE_GROUP:
        return f"组内 · {resource.group.name if resource.group is not None else (resource.group_id or '-')}"
    if resource.scope_type == SKILL_SCOPE_ORGANIZATION:
        return f"部门内 · {resource.scope_org_path or resource.scope_org_name or '-'}"
    return "公开"


def list_organization_scope_options(session: Session, actor: User) -> list[dict[str, Any]]:
    if actor.role.name == ROLE_ADMIN:
        rows = (
            session.query(
                User.org_level_1,
                User.org_level_2,
                User.org_level_3,
                User.org_level_4,
            )
            .filter(User.source == "AD")
            .all()
        )
        options: dict[tuple[int, str], dict[str, Any]] = {}
        for row in rows:
            levels = [item for item in row if (item or "").strip()]
            for index in range(1, len(levels) + 1):
                path = " / ".join(levels[:index])
                key = (index, path)
                if key in options:
                    continue
                options[key] = {
                    "level": index,
                    "name": levels[index - 1],
                    "path": path,
                    "is_leaf": index == len(levels),
                }
        return [options[key] for key in sorted(options, key=lambda item: (item[0], item[1]))]

    levels = actor_organization_levels(actor)
    if not levels:
        return []
    return [
        {
            "level": len(levels),
            "name": levels[-1],
            "path": " / ".join(levels),
            "is_leaf": True,
        }
    ]


def resolve_visibility_scope(
    session: Session,
    actor: User,
    *,
    scope_type: str | None,
    group_id: int | None,
    scope_org_level: int | None,
    scope_org_name: str | None,
    scope_org_path: str | None,
    entity_label: str,
) -> tuple[str, Group | None, int | None, str | None, str | None]:
    normalized_scope_type = normalize_scope_type(scope_type)
    if normalized_scope_type == SKILL_SCOPE_PUBLIC:
        return normalized_scope_type, None, None, None, None
    if normalized_scope_type == SKILL_SCOPE_GROUP:
        group = resolve_group_for_skill_binding(session, actor, group_id)
        if group is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="组范围必须选择归属组")
        return normalized_scope_type, group, None, None, None

    normalized_level, normalized_name, normalized_path = normalize_org_scope_payload(
        scope_org_level,
        scope_org_name,
        scope_org_path,
    )
    assert normalized_level is not None
    assert normalized_name is not None
    assert normalized_path is not None

    valid_options = list_organization_scope_options(session, actor)
    matched = next(
        (
            option for option in valid_options
            if option["level"] == normalized_level
            and option["name"] == normalized_name
            and option["path"] == normalized_path
        ),
        None,
    )
    if matched is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"无权将 {entity_label} 绑定到该组织范围")
    if actor.role.name != ROLE_ADMIN and not matched["is_leaf"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="普通用户只能绑定当前末级组织")
    return normalized_scope_type, None, normalized_level, normalized_name, normalized_path
