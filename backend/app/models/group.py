from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


GROUP_MEMBERSHIP_PENDING = "PENDING"
GROUP_MEMBERSHIP_ACTIVE = "ACTIVE"
GROUP_MEMBERSHIP_DECLINED = "DECLINED"
GROUP_MEMBERSHIP_CANCELLED = "CANCELLED"
GROUP_MEMBERSHIP_REMOVED = "REMOVED"


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 兼容旧数据库时先允许为空，启动时由 schema compatibility 按组长回填。
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    leader_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
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

    creator: Mapped["User | None"] = relationship(
        back_populates="created_groups",
        foreign_keys=[created_by_user_id],
        lazy="joined",
    )
    leader: Mapped["User"] = relationship(back_populates="led_groups", foreign_keys=[leader_user_id], lazy="joined")
    memberships: Mapped[list["GroupMembership"]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
        order_by="GroupMembership.id.asc()",
    )
    skills: Mapped[list["Skill"]] = relationship(back_populates="group")
    collections: Mapped[list["SkillCollection"]] = relationship(back_populates="group")


class GroupMembership(Base):
    __tablename__ = "group_memberships"
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_group_memberships_group_id_user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=GROUP_MEMBERSHIP_ACTIVE,
        server_default=GROUP_MEMBERSHIP_ACTIVE,
        index=True,
    )
    invited_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    group: Mapped[Group] = relationship(back_populates="memberships")
    user: Mapped["User"] = relationship(
        back_populates="group_memberships",
        foreign_keys=[user_id],
        lazy="joined",
    )
    invited_by: Mapped["User | None"] = relationship(
        foreign_keys=[invited_by_user_id],
        lazy="joined",
    )
