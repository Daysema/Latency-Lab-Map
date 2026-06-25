#!/usr/bin/env python3
"""Merge DNR/LNR regions and cities into public/data without re-downloading all cities."""
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "public" / "data"

DNR_LNR_REGIONS = {
    "Donets'k": {
        "name": "Донецкая Народная Республика",
        "name_en": "Donetsk People's Republic",
        "code": "RU-DON",
    },
    "Luhans'k": {
        "name": "Луганская Народная Республика",
        "name_en": "Luhansk People's Republic",
        "code": "RU-LUG",
    },
}

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
    geo = json.loads(
        urllib.request.urlopen(
            "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
            "master/geojson/ne_10m_admin_1_states_provinces.geojson",
            timeout=120,
        ).read()
    )

    regions = json.loads((DATA / "regions.geojson").read_text(encoding="utf-8"))
    existing_regions = {f["properties"]["name"] for f in regions["features"]}
    for feature in geo["features"]:
        props = feature["properties"]
        meta = DNR_LNR_REGIONS.get(props.get("name"))
        if not meta or meta["name"] in existing_regions:
            continue
        regions["features"].append(
            {
                "type": "Feature",
                "properties": meta,
                "geometry": feature["geometry"],
            }
        )
        existing_regions.add(meta["name"])

    (DATA / "regions.geojson").write_text(
        json.dumps(regions, ensure_ascii=False), encoding="utf-8"
    )
    print(f"regions: {len(regions['features'])}")

    cities = json.loads((DATA / "cities.json").read_text(encoding="utf-8"))
    extra = json.loads((DATA / "extra_cities.json").read_text(encoding="utf-8"))
    existing_cities = {(c["name"], c.get("subject", "")) for c in cities}
    added = 0
    for item in extra:
        key = (item["name"], item.get("subject", ""))
        if key in existing_cities:
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
        existing_cities.add(key)
        added += 1

    cities.sort(key=lambda c: (-c["population"], c["name"]))
    (DATA / "cities.json").write_text(
        json.dumps(cities, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"cities added: {added}, total: {len(cities)}")


if __name__ == "__main__":
    main()
