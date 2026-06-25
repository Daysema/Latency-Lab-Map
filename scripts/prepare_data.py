#!/usr/bin/env python3
"""Download and prepare map data for Latency Lab Map."""
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "public" / "data"

CITIES_URL = "https://raw.githubusercontent.com/pensnarik/russian-cities/master/russian-cities.json"
REGIONS_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_50m_admin_1_states_provinces.geojson"
)

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


def fetch(url: str) -> bytes:
    print(f"Fetching {url} ...")
    return urllib.request.urlopen(url, timeout=120).read()


def prepare_cities(raw: list) -> list:
    cities = []
    for item in raw:
        name = item["name"]
        pop = int(item.get("population") or 0)
        cities.append(
            {
                "name": name,
                "lat": float(item["coords"]["lat"]),
                "lng": float(item["coords"]["lon"]),
                "population": pop,
                "subject": item.get("subject", ""),
                "tier": tier(pop, name),
                "status": "unknown",
                "statusUpdatedAt": None,
                "comment": None,
            }
        )
    cities.sort(key=lambda c: (-c["population"], c["name"]))
    return cities


def prepare_regions(geo: dict) -> dict:
    features = []
    for f in geo["features"]:
        props = f["properties"]
        if props.get("adm0_a3") != "RUS":
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "name": props.get("name_ru") or props.get("name", ""),
                    "name_en": props.get("name_en") or props.get("name", ""),
                    "code": props.get("iso_3166_2", ""),
                },
                "geometry": f["geometry"],
            }
        )
    return {"type": "FeatureCollection", "features": features}


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)

    cities_raw = json.loads(fetch(CITIES_URL).decode("utf-8"))
    cities = prepare_cities(cities_raw)
    (DATA / "cities.json").write_text(
        json.dumps(cities, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Wrote {len(cities)} cities")

    regions_raw = json.loads(fetch(REGIONS_URL).decode("utf-8"))
    regions = prepare_regions(regions_raw)
    (DATA / "regions.geojson").write_text(
        json.dumps(regions, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Wrote {len(regions['features'])} regions")

    # Remove temporary downloads if present
    for tmp in ("regions.topojson", "regions-named.topojson", "cities-raw.json"):
        p = DATA / tmp
        if p.exists():
            p.unlink()


if __name__ == "__main__":
    main()
