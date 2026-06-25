#!/usr/bin/env python3
"""Align DNR/LNR borders with neighboring Russian regions (snap + clip overlaps)."""
import json
from pathlib import Path

from shapely import make_valid
from shapely.geometry import Point, mapping, shape
from shapely.ops import snap, unary_union

ROOT = Path(__file__).resolve().parents[1]
REGIONS_PATH = ROOT / "public" / "data" / "regions.geojson"

DNR_LNR = {
    "Донецкая Народная Республика",
    "Луганская Народная Республика",
}

NEIGHBORS = {
    "Донецкая Народная Республика": (
        "Луганская Народная Республика",
        "Ростовская область",
    ),
    "Луганская Народная Республика": (
        "Донецкая Народная Республика",
        "Ростовская область",
        "Белгородская область",
        "Воронежская область",
    ),
}

SNAP_TOLERANCE = 0.012  # ~1 km at these latitudes
MIN_OVERLAP = 1e-9
CITY_TRANSFER_RADIUS = 0.07  # ~7 km around misplaced oblast cities

FEDERAL_TO_OBLAST = {
    "Москва": "Московская область",
    "Санкт-Петербург": "Ленинградская область",
}


def _load_geoms(features: list[dict]) -> dict[str, object]:
    return {
        feature["properties"]["name"]: make_valid(shape(feature["geometry"]))
        for feature in features
    }


def _apply_geoms(features: list[dict], geoms: dict[str, object]) -> None:
    for feature in features:
        name = feature["properties"]["name"]
        if name in geoms and not geoms[name].is_empty:
            feature["geometry"] = mapping(geoms[name])


def fix_region_borders(features: list[dict]) -> list[dict]:
    geoms = _load_geoms(features)
    russian = [geom for name, geom in geoms.items() if name not in DNR_LNR]
    if not russian:
        return features

    rus_union = unary_union(russian)

    for name in DNR_LNR:
        if name not in geoms:
            continue

        geom = geoms[name]
        for neighbor in NEIGHBORS.get(name, ()):
            if neighbor in geoms:
                geom = snap(geom, geoms[neighbor], SNAP_TOLERANCE)
        geom = snap(geom, rus_union, SNAP_TOLERANCE)

        overlap = geom.intersection(rus_union)
        if overlap.area > MIN_OVERLAP:
            geom = geom.difference(rus_union)

        geoms[name] = make_valid(geom)

    dnr = geoms.get("Донецкая Народная Республика")
    lnr = geoms.get("Луганская Народная Республика")
    if dnr is not None and lnr is not None:
        dnr = snap(dnr, lnr, SNAP_TOLERANCE)
        lnr = snap(lnr, dnr, SNAP_TOLERANCE)
        overlap = dnr.intersection(lnr)
        if overlap.area > MIN_OVERLAP:
            lnr = lnr.difference(dnr)
        geoms["Донецкая Народная Республика"] = make_valid(dnr)
        geoms["Луганская Народная Республика"] = make_valid(lnr)

    _apply_geoms(features, geoms)
    return features


def fix_federal_city_boundaries(
    features: list[dict], cities: list[dict]
) -> list[dict]:
    """Move oblast cities out of oversized federal-city polygons (e.g. Podolsk)."""
    geoms = _load_geoms(features)

    for federal, oblast in FEDERAL_TO_OBLAST.items():
        if federal not in geoms or oblast not in geoms:
            continue

        federal_geom = geoms[federal]
        oblast_geom = geoms[oblast]
        transfer_parts = []

        for city in cities:
            if city.get("subject") != oblast:
                continue
            point = Point(city["lng"], city["lat"])
            if federal_geom.contains(point) and not oblast_geom.contains(point):
                zone = point.buffer(CITY_TRANSFER_RADIUS)
                part = federal_geom.intersection(zone)
                if not part.is_empty and part.area > MIN_OVERLAP:
                    transfer_parts.append(part)

        if not transfer_parts:
            continue

        transfer = unary_union(transfer_parts)
        geoms[federal] = make_valid(federal_geom.difference(transfer))
        geoms[oblast] = make_valid(oblast_geom.union(transfer))

    _apply_geoms(features, geoms)
    return features


def main() -> None:
    data = json.loads(REGIONS_PATH.read_text(encoding="utf-8"))
    cities_path = ROOT / "public" / "data" / "cities.json"
    cities = (
        json.loads(cities_path.read_text(encoding="utf-8"))
        if cities_path.exists()
        else []
    )
    fix_region_borders(data["features"])
    fix_federal_city_boundaries(data["features"], cities)
    REGIONS_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"Fixed borders in {REGIONS_PATH}")


if __name__ == "__main__":
    main()
