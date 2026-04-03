from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.db.base import Base


SKILL_COLUMNS = {
    "contributor": "ALTER TABLE skills ADD COLUMN contributor VARCHAR(128)",
    "current_version": "ALTER TABLE skills ADD COLUMN current_version VARCHAR(16) NOT NULL DEFAULT '1.0.0'",
    "deleted_at": "ALTER TABLE skills ADD COLUMN deleted_at DATETIME",
}


def ensure_schema_compatibility(engine: Engine) -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "skills" not in table_names:
        return

    _ensure_skill_columns(engine, inspector)
    Base.metadata.tables["skill_versions"].create(bind=engine, checkfirst=True)
    _backfill_skill_versions(engine)


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
