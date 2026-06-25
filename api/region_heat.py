"""Server-side IDW heat raster for a single region."""

from __future__ import annotations

import io
import json
import math
import threading
from pathlib import Path

from fastapi import HTTPException
from PIL import Image

SUBJECT_ALIASES = {
    "Алтай": "Республика Алтай",
    "Башкортостан": "Республика Башкортостан",
    "Коми": "Республика Коми",
    "Крым": "Автономная Республика Крым",
    "ДНР": "Донецкая Народная Республика",
    "ЛНР": "Луганская Народная Республика",
    "Северная Осетия": "Республика Северная Осетия-Алания",
    "Еврейская АО": "Еврейская автономная область",
    "Ненецкий АО": "Ненецкий автономный округ",
    "Ханты-Мансийский АО": "Ханты-Мансийский автономный округ — Югра",
    "Чукотский АО": "Чукотский автономный округ",
    "Ямало-Ненецкий АО": "Ямало-Ненецкий автономный округ",
}

INTENSITY_WEIGHT = {
    "unknown": 0.0,
    "ok": 0.0,
    "temp_rare": 0.35,
    "temp_frequent": 0.65,
    "permanent": 1.0,
}

HEAT_STOPS = (
    (0.0, (100, 116, 139)),
    (0.25, (34, 197, 94)),
    (0.5, (234, 179, 8)),
    (0.75, (249, 115, 22)),
    (1.0, (239, 68, 68)),
)

OK_RGB = (34, 197, 94)
UNKNOWN_RGBA = (100, 116, 139, 28)

IDW_POWER = 2
IDW_MAX_KM = 450

_regions_by_name: dict[str, dict] | None = None
_regions_lock = threading.Lock()


def normalize_subject(subject: str) -> str:
    return SUBJECT_ALIASES.get(subject, subject)


def _load_regions(regions_path: Path) -> dict[str, dict]:
    global _regions_by_name
    with _regions_lock:
        if _regions_by_name is not None:
            return _regions_by_name
        text = regions_path.read_text(encoding="utf-8")
        data = json.loads(text)
        _regions_by_name = {
            feature["properties"]["name"]: feature
            for feature in data.get("features", [])
            if feature.get("properties", {}).get("name")
        }
        return _regions_by_name


def invalidate_regions_cache() -> None:
    global _regions_by_name
    with _regions_lock:
        _regions_by_name = None


def _ring_coords(ring: list) -> list[tuple[float, float]]:
    return [(pt[0], pt[1]) for pt in ring]


def _point_in_ring(lng: float, lat: float, ring: list) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / (yj - yi + 1e-15) + xi:
            inside = not inside
        j = i
    return inside


def _point_in_feature(lng: float, lat: float, feature: dict) -> bool:
    geometry = feature.get("geometry") or {}
    gtype = geometry.get("type")

    if gtype == "Polygon":
        rings = geometry.get("coordinates") or []
        if not rings or not _point_in_ring(lng, lat, rings[0]):
            return False
        for hole in rings[1:]:
            if _point_in_ring(lng, lat, hole):
                return False
        return True

    if gtype == "MultiPolygon":
        for polygon in geometry.get("coordinates") or []:
            if not polygon or not _point_in_ring(lng, lat, polygon[0]):
                continue
            in_hole = any(_point_in_ring(lng, lat, hole) for hole in polygon[1:])
            if not in_hole:
                return True
    return False


def _feature_bounds(feature: dict) -> tuple[float, float, float, float]:
    south = math.inf
    west = math.inf
    north = -math.inf
    east = -math.inf

    geometry = feature.get("geometry") or {}
    coords = geometry.get("coordinates") or []

    def visit(lng: float, lat: float) -> None:
        nonlocal south, west, north, east
        south = min(south, lat)
        north = max(north, lat)
        west = min(west, lng)
        east = max(east, lng)

    if geometry.get("type") == "Polygon":
        for ring in coords:
            for lng, lat, *_ in ring:
                visit(lng, lat)
    elif geometry.get("type") == "MultiPolygon":
        for polygon in coords:
            for ring in polygon:
                for lng, lat, *_ in ring:
                    visit(lng, lat)

    if not math.isfinite(south):
        raise HTTPException(status_code=500, detail="Не удалось вычислить границы региона")
    return south, west, north, east


def _distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    to_rad = math.radians
    d_lat = to_rad(lat2 - lat1)
    d_lng = to_rad(lng2 - lng1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(to_rad(lat1)) * math.cos(to_rad(lat2)) * math.sin(d_lng / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _heat_rgb(intensity: float) -> tuple[int, int, int]:
    value = max(0.0, min(1.0, intensity))
    for i in range(len(HEAT_STOPS) - 1):
        left_t, left_rgb = HEAT_STOPS[i]
        right_t, right_rgb = HEAT_STOPS[i + 1]
        if value <= right_t:
            span = right_t - left_t or 1.0
            t = (value - left_t) / span
            return tuple(
                int(left_rgb[j] + (right_rgb[j] - left_rgb[j]) * t) for j in range(3)
            )
    return HEAT_STOPS[-1][1]


def _rgba_for_intensity(intensity: float | None, *, has_known: bool) -> tuple[int, int, int, int]:
    if not has_known:
        return UNKNOWN_RGBA
    if intensity is None:
        return (0, 0, 0, 0)
    if intensity <= 0.02:
        alpha = int(70 + (1.0 - intensity) * 40)
        return (*OK_RGB, alpha)
    alpha = int(45 + intensity * 150)
    rgb = _heat_rgb(intensity)
    return (*rgb, alpha)


def _interpolate_idw(lat: float, lng: float, cities: list[dict]) -> float | None:
    sources = [c for c in cities if c.get("status") not in (None, "", "unknown")]
    if not sources:
        return None

    sum_w = 0.0
    sum_wv = 0.0
    for city in sources:
        dist = max(_distance_km(lat, lng, city["lat"], city["lng"]), 0.3)
        if dist > IDW_MAX_KM:
            continue
        weight = 1.0 / (dist**IDW_POWER)
        value = INTENSITY_WEIGHT.get(city.get("status", "unknown"), 0.0)
        sum_w += weight
        sum_wv += weight * value

    if sum_w == 0:
        city = sources[0]
        return INTENSITY_WEIGHT.get(city.get("status", "unknown"), 0.0)
    return sum_wv / sum_w


def _cities_for_region(region_name: str, cities: list[dict]) -> list[dict]:
    return [
        city
        for city in cities
        if normalize_subject(city.get("subject") or "") == region_name
    ]


def render_region_heat_png(
    *,
    region_name: str,
    cities: list[dict],
    regions_path: Path,
    width: int = 180,
) -> bytes:
    regions = _load_regions(regions_path)
    feature = regions.get(region_name)
    if feature is None:
        raise HTTPException(status_code=404, detail="Регион не найден")

    width = max(64, min(width, 256))
    south, west, north, east = _feature_bounds(feature)
    lat_span = max(north - south, 0.01)
    lng_span = max(east - west, 0.01)
    mid_lat = (south + north) / 2
    aspect = lat_span / (lng_span * max(math.cos(math.radians(mid_lat)), 0.2))
    height = max(48, min(256, int(width * aspect)))

    regional_cities = _cities_for_region(region_name, cities)
    known = [c for c in regional_cities if c.get("status") not in (None, "", "unknown")]

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pixels = image.load()
    assert pixels is not None

    for py in range(height):
        lat = north - (py / height) * lat_span
        for px in range(width):
            lng = west + (px / width) * lng_span
            if not _point_in_feature(lng, lat, feature):
                continue
            intensity = _interpolate_idw(lat, lng, regional_cities)
            rgba = _rgba_for_intensity(intensity, has_known=bool(known))
            pixels[px, py] = rgba

    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
