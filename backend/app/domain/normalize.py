"""Deterministic alias lookup. Unknown names keep their raw spelling and category."""

from dataclasses import dataclass
from pathlib import Path

from pydantic import TypeAdapter
from rapidfuzz.fuzz import ratio

from app.config import FUZZY_MATCH_THRESHOLD, ROOT
from app.domain.schemas import Category, DomainModel, Kind, Name


class Alias(DomainModel):
    alias: Name
    canonical: Name
    kind: Kind
    category: Category


@dataclass(frozen=True)
class NormalizedName:
    canonical: str
    raw_name: str
    kind: Kind | None
    category: str


def clean_name(value: str) -> str:
    return " ".join(value.casefold().split())


def load_aliases(path: Path = ROOT / "data" / "aliases.json") -> tuple[Alias, ...]:
    aliases = TypeAdapter(list[Alias]).validate_json(path.read_bytes())
    seen: set[str] = set()
    for alias in aliases:
        key = clean_name(alias.alias)
        if key in seen:
            raise ValueError(f"Duplicate alias: {key}")
        seen.add(key)
    return tuple(sorted(aliases, key=lambda alias: (clean_name(alias.alias), alias.canonical)))


def normalize(name: str, aliases: tuple[Alias, ...] | None = None) -> NormalizedName:
    catalog = load_aliases() if aliases is None else aliases
    key = clean_name(name)
    if not key:
        raise ValueError("Name cannot be empty")
    ranked = sorted(
        catalog,
        key=lambda alias: (-ratio(key, clean_name(alias.alias)), alias.canonical, alias.alias),
    )
    if ranked and ratio(key, clean_name(ranked[0].alias)) >= FUZZY_MATCH_THRESHOLD:
        match = ranked[0]
        return NormalizedName(match.canonical, name, match.kind, match.category)
    return NormalizedName(name, name, None, "unknown")
