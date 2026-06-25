#!/usr/bin/env python3
"""Idempotently merge extra_cities.json into the persistent cities file."""
import json
import os
from pathlib import Path

CITIES_PATH = Path(os.environ.get("CITIES_PATH", "/data/cities.json"))
EXTRA_PATH = Path(os.environ.get("EXTRA_CITIES_PATH", "/seed/extra_cities.json"))

CAPITALS = {"Москва", "Санкт-Петербург"}


def tier(population: int, name: str) -> str:
    if name in CAPITALS:
        return "capital"
    if population >= 1_000_000:
        return "megacity"
    if population >= 500_000:
        return "large"
    if population >= 100_000:
        return "regional"
    if population >= 20_000:
        return "small"
    return "town"


def main() -> None:
    if not EXTRA_PATH.exists() or not CITIES_PATH.exists():
        return

    cities = json.loads(CITIES_PATH.read_text(encoding="utf-8"))
    extra = json.loads(EXTRA_PATH.read_text(encoding="utf-8"))
    existing = {(c["name"], c.get("subject", "")) for c in cities}
    added = 0

    for item in extra:
        key = (item["name"], item.get("subject", ""))
        if key in existing:
            continue
        pop = int(item.get("population") or 0)
        cities.append(
            {
                "name": item["name"],
                "lat": float(item["lat"]),
                "lng": float(item["lng"]),
                "population": pop,
                "subject": item.get("subject", ""),
                "tier": tier(pop, item["name"]),
                "status": "unknown",
                "statusUpdatedAt": None,
                "comment": None,
            }
        )
        existing.add(key)
        added += 1

    if not added:
        return

    cities.sort(key=lambda c: (-c["population"], c["name"]))
    tmp = CITIES_PATH.with_name(f"{CITIES_PATH.name}.merge.tmp")
    tmp.write_text(json.dumps(cities, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CITIES_PATH)
    print(f"Merged {added} extra cities into {CITIES_PATH}")


if __name__ == "__main__":
    main()
