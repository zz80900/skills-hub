from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.skill import SKILL_SCOPE_PUBLIC


COLLECTION_MANIFEST_SCHEMA_VERSION = "nexgo.collection.v1"


class SkillCollection(Base):
    __tablename__ = "skill_collections"
    __table_args__ = (
        Index(
            "uq_skill_collections_active_slug",
            "slug",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"), nullable=True, index=True)
    scope_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=SKILL_SCOPE_PUBLIC,
        server_default=SKILL_SCOPE_PUBLIC,
    )
    scope_org_level: Mapped[int | None] = mapped_column(nullable=True)
    scope_org_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scope_org_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    description_markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description_html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    contributor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    package_url: Mapped[str] = mapped_column(String(512), nullable=False)
    current_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0.0")
    manifest_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    item_count: Mapped[int] = mapped_column(nullable=False, default=0)
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

    snapshots: Mapped[list["SkillCollectionSnapshot"]] = relationship(
        back_populates="collection",
        cascade="all, delete-orphan",
        order_by="SkillCollectionSnapshot.id.desc()",
    )
    owner: Mapped["User"] = relationship(back_populates="collections", lazy="joined")
    group: Mapped["Group"] = relationship(back_populates="collections", lazy="joined")


class SkillCollectionSnapshot(Base):
    __tablename__ = "skill_collection_snapshots"
    __table_args__ = (
        UniqueConstraint("collection_id", "version", name="uq_skill_collection_snapshots_collection_id_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("skill_collections.id"), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    package_url: Mapped[str] = mapped_column(String(512), nullable=False)
    manifest_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    item_count: Mapped[int] = mapped_column(nullable=False, default=0)
    description_markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description_html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    contributor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    collection: Mapped[SkillCollection] = relationship(back_populates="snapshots")
