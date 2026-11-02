"""Short-lived administrator drafts for forwarded-message registration."""

from __future__ import annotations

from dataclasses import dataclass, field

from bot.services.deep_links import validate_website_id


@dataclass(slots=True)
class RegistrationDraft:
    website_id: str
    title: str
    strip_captions: bool
    message_ids: list[int] = field(default_factory=list)

    def add_message(self, message_id: int) -> bool:
        if message_id in self.message_ids:
            return False
        if len(self.message_ids) >= 100:
            raise ValueError("A resource cannot contain more than 100 messages")
        self.message_ids.append(message_id)
        return True


class RegistrationDraftStore:
    """Process-local drafts; committed mappings remain persistent in SQLite."""

    def __init__(self) -> None:
        self._drafts: dict[int, RegistrationDraft] = {}

    def begin(
        self,
        user_id: int,
        website_id: str,
        title: str,
        *,
        strip_captions: bool = True,
    ) -> RegistrationDraft:
        website_id = validate_website_id(website_id)
        title = title.strip()
        if not title or len(title) > 200:
            raise ValueError("Title must contain 1-200 characters")
        draft = RegistrationDraft(website_id, title, strip_captions)
        self._drafts[user_id] = draft
        return draft

    def get(self, user_id: int) -> RegistrationDraft | None:
        return self._drafts.get(user_id)

    def abort(self, user_id: int) -> bool:
        return self._drafts.pop(user_id, None) is not None

    def finish(self, user_id: int) -> RegistrationDraft | None:
        return self._drafts.pop(user_id, None)
