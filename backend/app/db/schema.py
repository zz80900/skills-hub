from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.models.user import Role, User
from app.services.user_service import ROLE_ADMIN, ROLE_USER


SKILL_COLUMNS = {
    "contributor": "ALTER TABLE skills ADD COLUMN contributor VARCHAR(128)",
    "current_version": "ALTER TABLE skills ADD COLUMN current_version VARCHAR(16) NOT NULL DEFAULT '1.0.0'",
    "deleted_at": "ALTER TABLE skills ADD COLUMN deleted_at TIMESTAMP WITH TIME ZONE",
    "owner_id": "ALTER TABLE skills ADD COLUMN owner_id INTEGER",
}


def ensure_schema_compatibility(engine: Engine) -> None:
    Base.metadata.tables["roles"].create(bind=engine, checkfirst=True)
    Base.metadata.tables["users"].create(bind=engine, checkfirst=True)
    Base.metadata.tables["skill_versions"].create(bind=engine, checkfirst=True)
    default_admin_id = _ensure_access_control_seed_data(engine)

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "skills" not in table_names:
        return

    _ensure_skill_columns(engine, inspector)
    _backfill_skill_versions(engine)
    _backfill_skill_owners(engine, default_admin_id)


def _ensure_skill_columns(engine: Engine, inspector) -> None:
    column_names = {column["name"] for column in inspector.get_columns("skills")}
    missing_columns = {name: ddl for name, ddl in SKILL_COLUMNS.items() if name not in column_names}
    if not missing_columns:
        return

    try:
        with engine.begin() as connection:
            for ddl in missing_columns.values():
                connection.execute(text(ddl))
    except SQLAlchemyError:
        refreshed_column_names = {column["name"] for column in inspect(engine).get_columns("skills")}
        if all(name in refreshed_column_names for name in missing_columns):
            return
        raise


def _backfill_skill_versions(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE skills
                SET current_version = '1.0.0'
                WHERE current_version IS NULL OR TRIM(current_version) = ''
                """
            )
        )

        rows = connection.execute(
            text(
                """
                SELECT
                    skills.id,
                    skills.current_version,
                    skills.description_markdown,
                    skills.description_html,
                    skills.contributor,
                    skills.package_url,
                    skills.updated_at
                FROM skills
                LEFT JOIN skill_versions
                    ON skill_versions.skill_id = skills.id
                    AND skill_versions.version = skills.current_version
                WHERE skill_versions.id IS NULL
                """
            )
        ).mappings()

        for row in rows:
            connection.execute(
                text(
                    """
                    INSERT INTO skill_versions (
                        skill_id,
                        version,
                        description_markdown,
                        description_html,
                        contributor,
                        package_url,
                        created_at
                    ) VALUES (
                        :skill_id,
                        :version,
                        :description_markdown,
                        :description_html,
                        :contributor,
                        :package_url,
                        :created_at
                    )
                    """
                ),
                {
                    "skill_id": row["id"],
                    "version": row["current_version"] or "1.0.0",
                    "description_markdown": row["description_markdown"] or "",
                    "description_html": row["description_html"] or "",
                    "contributor": row["contributor"],
                    "package_url": row["package_url"],
                    "created_at": row["updated_at"],
                },
            )


def _ensure_access_control_seed_data(engine: Engine) -> int:
    settings = get_settings()
    seed_username = ((settings.admin_username or "admin").strip().lower() or "admin")
    seed_password = settings.admin_password or "admin"

    with Session(engine) as session:
        admin_role = session.query(Role).filter(Role.name == ROLE_ADMIN).one_or_none()
        if admin_role is None:
            admin_role = Role(name=ROLE_ADMIN, description="管理员")
            session.add(admin_role)

        user_role = session.query(Role).filter(Role.name == ROLE_USER).one_or_none()
        if user_role is None:
            user_role = Role(name=ROLE_USER, description="普通用户")
            session.add(user_role)

        session.flush()

        admin_user = session.query(User).filter(User.username == seed_username).one_or_none()
        if admin_user is None:
            admin_user = User(
                username=seed_username,
                password_hash=hash_password(seed_password),
                role_id=admin_role.id,
                is_active=True,
            )
            session.add(admin_user)
        else:
            if admin_user.role_id != admin_role.id:
                admin_user.role_id = admin_role.id
            if not admin_user.is_active:
                admin_user.is_active = True
            session.add(admin_user)

        session.commit()
        session.refresh(admin_user)
        return admin_user.id


def _backfill_skill_owners(engine: Engine, default_admin_id: int) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE skills
                SET owner_id = :owner_id
                WHERE owner_id IS NULL
                """
            ),
            {"owner_id": default_admin_id},
        )
