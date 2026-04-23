import re

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.models.user import Role, User, USER_SOURCE_LOCAL
from app.services.user_service import ROLE_ADMIN, ROLE_USER


SKILL_COLUMNS = {
    "contributor": "ALTER TABLE skills ADD COLUMN contributor VARCHAR(128)",
    "current_version": "ALTER TABLE skills ADD COLUMN current_version VARCHAR(16) NOT NULL DEFAULT '1.0.0'",
    "deleted_at": "ALTER TABLE skills ADD COLUMN deleted_at TIMESTAMP WITH TIME ZONE",
    "group_id": "ALTER TABLE skills ADD COLUMN group_id INTEGER",
    "owner_id": "ALTER TABLE skills ADD COLUMN owner_id INTEGER",
}
USER_COLUMNS = {
    "source": f"ALTER TABLE users ADD COLUMN source VARCHAR(16) NOT NULL DEFAULT '{USER_SOURCE_LOCAL}'",
    "display_name": "ALTER TABLE users ADD COLUMN display_name VARCHAR(128)",
    "external_principal": "ALTER TABLE users ADD COLUMN external_principal VARCHAR(255)",
}


def ensure_schema_compatibility(engine: Engine) -> None:
    Base.metadata.tables["roles"].create(bind=engine, checkfirst=True)
    Base.metadata.tables["users"].create(bind=engine, checkfirst=True)
    Base.metadata.tables["groups"].create(bind=engine, checkfirst=True)
    Base.metadata.tables["group_memberships"].create(bind=engine, checkfirst=True)
    Base.metadata.tables["skill_versions"].create(bind=engine, checkfirst=True)
    inspector = inspect(engine)
    _ensure_user_columns(engine, inspector)
    _backfill_user_sources(engine)

    default_admin_id = _ensure_access_control_seed_data(engine)
    table_names = set(inspector.get_table_names())
    if "skills" not in table_names:
        return

    _ensure_skill_columns(engine, inspector)
    _backfill_skill_versions(engine)
    _backfill_skill_owners(engine, default_admin_id)
    _ensure_group_leader_memberships(engine)
    _ensure_skill_name_uniqueness_policy(engine)
    _ensure_skill_indexes(engine)


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


def _ensure_user_columns(engine: Engine, inspector) -> None:
    column_names = {column["name"] for column in inspector.get_columns("users")}
    missing_columns = {name: ddl for name, ddl in USER_COLUMNS.items() if name not in column_names}
    if not missing_columns:
        return

    try:
        with engine.begin() as connection:
            for ddl in missing_columns.values():
                connection.execute(text(ddl))
    except SQLAlchemyError:
        refreshed_column_names = {column["name"] for column in inspect(engine).get_columns("users")}
        if all(name in refreshed_column_names for name in missing_columns):
            return
        raise


def _backfill_user_sources(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE users
                SET source = :source
                WHERE source IS NULL OR TRIM(source) = ''
                """
            ),
            {"source": USER_SOURCE_LOCAL},
        )


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
                source=USER_SOURCE_LOCAL,
                is_active=True,
            )
            session.add(admin_user)
        else:
            if admin_user.role_id != admin_role.id:
                admin_user.role_id = admin_role.id
            if not admin_user.is_active:
                admin_user.is_active = True
            if not admin_user.source:
                admin_user.source = USER_SOURCE_LOCAL
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


def _ensure_group_leader_memberships(engine: Engine) -> None:
    table_names = set(inspect(engine).get_table_names())
    if "groups" not in table_names or "group_memberships" not in table_names:
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO group_memberships (group_id, user_id, created_at)
                SELECT groups.id, groups.leader_user_id, CURRENT_TIMESTAMP
                FROM groups
                LEFT JOIN group_memberships
                    ON group_memberships.group_id = groups.id
                    AND group_memberships.user_id = groups.leader_user_id
                WHERE groups.leader_user_id IS NOT NULL
                  AND group_memberships.id IS NULL
                """
            )
        )


def _ensure_skill_name_uniqueness_policy(engine: Engine) -> None:
    dialect_name = engine.dialect.name
    if dialect_name == "sqlite":
        _ensure_sqlite_skill_name_uniqueness_policy(engine)
        return

    if dialect_name == "postgresql":
        _ensure_postgresql_skill_name_uniqueness_policy(engine)


def _ensure_sqlite_skill_name_uniqueness_policy(engine: Engine) -> None:
    table_sql = _get_sqlite_table_sql(engine, "skills")
    if table_sql and _sqlite_table_has_global_unique_name(table_sql):
        _rebuild_sqlite_skills_table_without_global_unique_name(engine)

    _drop_sqlite_global_unique_skill_name_indexes(engine)

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_skills_active_name
                ON skills (name)
                WHERE deleted_at IS NULL
                """
            )
        )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_skills_name ON skills (name)"))


def _get_sqlite_table_sql(engine: Engine, table_name: str) -> str | None:
    with engine.begin() as connection:
        return connection.execute(
            text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = :table_name"),
            {"table_name": table_name},
        ).scalar()


def _sqlite_table_has_global_unique_name(table_sql: str) -> bool:
    normalized_sql = re.sub(r"\s+", " ", table_sql.upper())
    return bool(
        re.search(r"\bNAME\b.*?\bUNIQUE\b", normalized_sql)
        or re.search(r"\bUNIQUE\s*\(\s*NAME\s*\)", normalized_sql)
    )


def _drop_sqlite_global_unique_skill_name_indexes(engine: Engine) -> None:
    with engine.begin() as connection:
        index_rows = connection.execute(text("PRAGMA index_list('skills')")).mappings().all()
        for row in index_rows:
            if not row["unique"]:
                continue

            index_name = row["name"]
            if not index_name or str(index_name).startswith("sqlite_autoindex_"):
                continue

            index_columns = connection.execute(
                text(f"PRAGMA index_info({_quote_sqlite_identifier(index_name)})")
            ).mappings().all()
            if [column["name"] for column in index_columns] != ["name"]:
                continue

            index_sql = connection.execute(
                text("SELECT sql FROM sqlite_master WHERE type = 'index' AND name = :name"),
                {"name": index_name},
            ).scalar()
            if _sqlite_is_active_name_unique_index(index_sql):
                continue

            connection.execute(text(f"DROP INDEX IF EXISTS {_quote_sqlite_identifier(index_name)}"))


def _sqlite_is_active_name_unique_index(index_sql: str | None) -> bool:
    if not index_sql:
        return False
    normalized_sql = re.sub(r"\s+", " ", index_sql.upper())
    return "ON SKILLS (NAME)" in normalized_sql and "WHERE DELETED_AT IS NULL" in normalized_sql


def _quote_sqlite_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def _rebuild_sqlite_skills_table_without_global_unique_name(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=OFF"))
        try:
            connection.execute(text("DROP TABLE IF EXISTS skills__migration"))
            connection.execute(
                text(
                    """
                    CREATE TABLE skills__migration (
                        id INTEGER NOT NULL PRIMARY KEY,
                        name VARCHAR(64) NOT NULL,
                        owner_id INTEGER NOT NULL,
                        group_id INTEGER,
                        description_markdown TEXT NOT NULL DEFAULT '',
                        description_html TEXT NOT NULL DEFAULT '',
                        contributor VARCHAR(128),
                        package_url VARCHAR(512) NOT NULL,
                        current_version VARCHAR(16) NOT NULL DEFAULT '1.0.0',
                        deleted_at TIMESTAMP,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(owner_id) REFERENCES users (id),
                        FOREIGN KEY(group_id) REFERENCES groups (id)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO skills__migration (
                        id,
                        name,
                        owner_id,
                        group_id,
                        description_markdown,
                        description_html,
                        contributor,
                        package_url,
                        current_version,
                        deleted_at,
                        created_at,
                        updated_at
                    )
                    SELECT
                        id,
                        name,
                        owner_id,
                        group_id,
                        description_markdown,
                        description_html,
                        contributor,
                        package_url,
                        current_version,
                        deleted_at,
                        created_at,
                        updated_at
                    FROM skills
                    """
                )
            )
            connection.execute(text("DROP TABLE skills"))
            connection.execute(text("ALTER TABLE skills__migration RENAME TO skills"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_skills_name ON skills (name)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_skills_owner_id ON skills (owner_id)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_skills_group_id ON skills (group_id)"))
        finally:
            connection.execute(text("PRAGMA foreign_keys=ON"))


def _ensure_postgresql_skill_name_uniqueness_policy(engine: Engine) -> None:
    with engine.begin() as connection:
        constraint_rows = connection.execute(
            text(
                """
                SELECT con.conname
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                JOIN pg_namespace nsp ON nsp.oid = con.connamespace
                WHERE rel.relname = 'skills'
                  AND nsp.nspname = current_schema()
                  AND con.contype = 'u'
                  AND pg_get_constraintdef(con.oid) ILIKE '%(name)%'
                """
            )
        ).scalars()
        for constraint_name in constraint_rows:
            connection.execute(
                text(f"ALTER TABLE skills DROP CONSTRAINT {_quote_postgresql_identifier(constraint_name)}")
            )

        index_rows = connection.execute(
            text(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND tablename = 'skills'
                """
            )
        ).mappings()
        for row in index_rows:
            index_name = row["indexname"]
            index_definition = row["indexdef"]
            if not _postgresql_is_legacy_global_unique_skill_name_index(index_definition):
                continue
            connection.execute(text(f"DROP INDEX IF EXISTS {_quote_postgresql_identifier(index_name)}"))

        connection.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_skills_active_name
                ON skills (name)
                WHERE deleted_at IS NULL
                """
            )
        )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_skills_name ON skills (name)"))


def _ensure_skill_indexes(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_skills_owner_id ON skills (owner_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_skills_group_id ON skills (group_id)"))


def _postgresql_is_legacy_global_unique_skill_name_index(index_sql: str | None) -> bool:
    if not index_sql:
        return False
    normalized_sql = re.sub(r"\s+", " ", index_sql.upper())
    if "CREATE UNIQUE INDEX" not in normalized_sql:
        return False
    if not re.search(r"\(\s*\"?NAME\"?\s*\)", normalized_sql):
        return False
    return not re.search(r"WHERE\s+\(?\s*\"?DELETED_AT\"?\s+IS\s+NULL\s*\)?", normalized_sql)


def _quote_postgresql_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'
