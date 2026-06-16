from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class OfficeStat:
    label: str
    value: str


@dataclass(frozen=True)
class OfficeCard:
    eyebrow: str
    title: str
    body: str
    items: tuple[dict[str, str], ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "eyebrow": self.eyebrow,
            "title": self.title,
            "body": self.body,
            "items": [dict(item) for item in self.items],
        }


@dataclass(frozen=True)
class OfficeSurfacePayload:
    title: str
    summary: str
    stats: tuple[OfficeStat, ...]
    cards: tuple[OfficeCard, ...]
    console_form: dict[str, Any] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "OfficeSurfacePayload":
        stats = tuple(
            OfficeStat(label=str(item.get("label") or ""), value=str(item.get("value") or ""))
            for item in list(payload.get("stats") or [])
            if isinstance(item, dict)
        )
        cards = tuple(
            OfficeCard(
                eyebrow=str(item.get("eyebrow") or ""),
                title=str(item.get("title") or ""),
                body=str(item.get("body") or ""),
                items=tuple(dict(row) for row in list(item.get("items") or []) if isinstance(row, dict)),
            )
            for item in list(payload.get("cards") or [])
            if isinstance(item, dict)
        )
        extras = {
            key: value
            for key, value in payload.items()
            if key not in {"title", "summary", "stats", "cards", "console_form"}
        }
        return cls(
            title=str(payload.get("title") or ""),
            summary=str(payload.get("summary") or ""),
            stats=stats,
            cards=cards,
            console_form=dict(payload.get("console_form") or {}),
            extras=extras,
        )

    def as_template_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "title": self.title,
            "summary": self.summary,
            "stats": [asdict(item) for item in self.stats],
            "cards": [item.as_dict() for item in self.cards],
            "console_form": dict(self.console_form),
        }
        payload.update(self.extras)
        return payload
