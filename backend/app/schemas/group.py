from pydantic import BaseModel, ConfigDict, Field


class GroupMemberSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str | None = None
    role: str
    source: str
    is_active: bool


class GroupSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    leader_user_id: int
    leader_username: str
    leader_display_name: str | None = None
    member_count: int
    members: list[GroupMemberSummary] = Field(default_factory=list)


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
    leader_user_id: int


class GroupUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    leader_user_id: int | None = None


class GroupMembersUpdateRequest(BaseModel):
    user_ids: list[int] = Field(default_factory=list)


class GroupMemberCreateRequest(BaseModel):
    user_id: int
