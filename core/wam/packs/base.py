"""Industry packs sit on top of the shared engine. The business `type` decides which pack loads."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from types import ModuleType


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
    # Dotted path of a module with the pack's own quick replies, AI tools and staff commands (optional).
    hooks: str | None = None

    def word(self, key: str) -> str:
        return self.vocab.get(key, key)

    def hook_module(self) -> ModuleType | None:
        """Imported lazily so packs can use the shared engine without import cycles."""
        return importlib.import_module(self.hooks) if self.hooks else None
