from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError


def ensure_schema_compatibility(engine: Engine) -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "skills" not in table_names:
        return

    column_names = {column["name"] for column in inspector.get_columns("skills")}
    if "contributor" in column_names:
        return

    try:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE skills ADD COLUMN contributor VARCHAR(128)"))
    except SQLAlchemyError:
        refreshed_column_names = {column["name"] for column in inspect(engine).get_columns("skills")}
        if "contributor" in refreshed_column_names:
            return
        raise
