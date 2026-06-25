#!/usr/bin/env python3
"""Align DNR/LNR borders with neighboring Russian regions (snap + clip overlaps)."""
import json
from pathlib import Path

from shapely import make_valid
from shapely.geometry import MultiPolygon, mapping, shape
from shapely.ops import snap, unary_union

ROOT = Path(__file__).resolve().parents[1]
REGIONS_PATH = ROOT / "public" / "data" / "regions.geojson"

DATELINE_LON = 180.0
DATELINE_SNAP = 0.02

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

MIN_OVERLAP = 1e-9

SNAP_TOLERANCE = 0.012  # ~1 km at these latitudes


def _shift_coord(lon: float, lat: float) -> list[float]:
    if lon < 0:
        lon += 360
    if abs(lon - DATELINE_LON) <= DATELINE_SNAP:
        lon = DATELINE_LON
    return [lon, lat]


def _shift_coords_recursive(coords):
    if isinstance(coords[0], (int, float)):
        return _shift_coord(coords[0], coords[1])
    return [_shift_coords_recursive(part) for part in coords]


def fix_antimeridian_geometry(geometry: dict) -> dict:
    return {
        "type": geometry["type"],
        "coordinates": _shift_coords_recursive(geometry["coordinates"]),
    }


def _unify_antimeridian_geom(geom):
    """Join shifted parts on one 180° meridian instead of split edges."""
    united = make_valid(unary_union(geom))
    return united


def fix_antimeridian(features: list[dict]) -> list[dict]:
    for feature in features:
        geom = shape(feature["geometry"])
        minx, _, maxx, _ = geom.bounds
        if maxx - minx <= 180:
            continue
        shifted = shape(fix_antimeridian_geometry(feature["geometry"]))
        fixed = _unify_antimeridian_geom(shifted)
        feature["geometry"] = mapping(fixed)
    return features


def _polygon_parts(geom) -> list:
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type == "MultiPolygon":
        return list(geom.geoms)
    return []


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
    fix_antimeridian(data["features"])
    REGIONS_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"Fixed borders in {REGIONS_PATH}")


if __name__ == "__main__":
    main()
