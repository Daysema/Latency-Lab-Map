#!/usr/bin/env python3
"""Align DNR/LNR borders with neighboring Russian regions (snap + clip overlaps)."""
import json
from pathlib import Path

from shapely import make_valid
from shapely.geometry import mapping, shape
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


def main() -> None:
    data = json.loads(REGIONS_PATH.read_text(encoding="utf-8"))
    fix_region_borders(data["features"])
    REGIONS_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"Fixed borders in {REGIONS_PATH}")


if __name__ == "__main__":
    main()
