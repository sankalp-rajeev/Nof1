"""Structured query intent and deterministic latest-date selection from read-only facts."""

import re
from datetime import date

from pydantic import JsonValue

from app.domain.normalize import load_aliases, normalize


def lookup_query(text: str) -> dict[str, JsonValue]:
    names = sorted(
        {
            alias.canonical
            for alias in load_aliases()
            if re.search(r"\b" + re.escape(alias.alias) + r"\b", text.casefold())
        }
    )
    return {
        "operation": "latest"
        if re.search(r"\b(?:last|latest|most recent)\b", text, re.I)
        else "summary",
        "names": list(names),
    }


def latest_matching_date(payload: dict[str, JsonValue]) -> str | None:
    query, results = payload.get("query"), payload.get("tool_results")
    if (
        not isinstance(query, dict)
        or query.get("operation") != "latest"
        or not isinstance(results, list)
    ):
        return None
    names = query.get("names")
    if not isinstance(names, list) or not names:
        return None
    wanted = {normalize(str(name)).canonical for name in names}
    dates: list[date] = []
    for result in results:
        if not isinstance(result, dict) or not isinstance(result.get("days"), dict):
            continue
        days = result["days"]
        assert isinstance(days, dict)
        for day, rows in days.items():
            if not isinstance(rows, list):
                continue
            if any(
                isinstance(row, dict) and normalize(str(row.get("name", ""))).canonical in wanted
                for row in rows
            ):
                try:
                    dates.append(date.fromisoformat(day))
                except ValueError:
                    pass
    return max(dates).isoformat() if dates else None
