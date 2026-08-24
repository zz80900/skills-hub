from pydantic import BaseModel, ConfigDict, Field


class GroupMemberSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str | None = None
    role: str
    source: str
    is_active: bool
    status: str = "ACTIVE"


class GroupInvitationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    membership_id: int
    group_id: int
    group_name: str
    leader_user_id: int
    leader_username: str
    user_id: int
    username: str
    display_name: str | None = None
    invited_by_user_id: int | None = None
    invited_by_username: str | None = None
    invited_at: str | None = None
    status: str


class GroupSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    leader_user_id: int
    leader_username: str
    leader_display_name: str | None = None
    created_by_user_id: int | None = None
    member_count: int
    members: list[GroupMemberSummary] = Field(default_factory=list)
    pending_invitation_count: int = 0
    pending_invitations: list[GroupInvitationSummary] = Field(default_factory=list)


class GroupOption(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    leader_user_id: int
    leader_username: str


class GroupCreateRequest(BaseModel):
    name: str
    description: str | None = None
    leader_user_id: int | None = None


class GroupUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    leader_user_id: int | None = None


class GroupMembersUpdateRequest(BaseModel):
    user_ids: list[int] = Field(default_factory=list)


class GroupMemberCreateRequest(BaseModel):
    user_id: int


class GroupLeaderUpdateRequest(BaseModel):
    leader_user_id: int
