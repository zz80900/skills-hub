from typing import Literal

from pydantic import BaseModel

from app.schemas.collection import PublicCollectionSummary
from app.schemas.skill import PublicSkillSummary


class PublicLocalLibrarySkillItem(PublicSkillSummary):
    kind: Literal["skill"] = "skill"


class PublicLocalLibraryCollectionItem(PublicCollectionSummary):
    kind: Literal["collection"] = "collection"


PublicLocalLibraryItem = PublicLocalLibrarySkillItem | PublicLocalLibraryCollectionItem


class PublicLocalLibraryResponse(BaseModel):
    items: list[PublicLocalLibraryItem]
