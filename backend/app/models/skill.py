from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Skill(Base):
    __tablename__ = "skills"
    __table_args__ = (
        Index(
            "uq_skills_active_name",
            "name",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"), nullable=True, index=True)
    description_markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description_html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    contributor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    package_url: Mapped[str] = mapped_column(String(512), nullable=False)
    current_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0.0")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    versions: Mapped[list["SkillVersion"]] = relationship(
        back_populates="skill",
        cascade="all, delete-orphan",
        order_by="SkillVersion.id.desc()",
    )
    owner: Mapped["User"] = relationship(back_populates="skills", lazy="joined")
    group: Mapped["Group"] = relationship(back_populates="skills", lazy="joined")


class SkillVersion(Base):
    __tablename__ = "skill_versions"
    __table_args__ = (UniqueConstraint("skill_id", "version", name="uq_skill_versions_skill_id_version"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id"), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    description_markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description_html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    contributor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    package_url: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    skill: Mapped[Skill] = relationship(back_populates="versions")
