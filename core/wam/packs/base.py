"""Industry packs sit on top of the shared engine. The business `type` decides which pack loads."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Pack:
    type: str
    label: str
    vocab: dict[str, str]
    starter_templates: list[dict] = field(default_factory=list)
    default_roles: dict[str, list[str]] = field(default_factory=dict)
    medical: bool = False
    ai_rules: str = ""
    # Whether patients/customers can self-book through the AI tools.
    booking_enabled: bool = True

    def word(self, key: str) -> str:
        return self.vocab.get(key, key)
