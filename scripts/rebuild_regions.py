#!/usr/bin/env python3
"""Rebuild regions.geojson from ne_10m and align DNR/LNR borders."""
import json
import urllib.request
from pathlib import Path

from fix_region_borders import fix_region_borders

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "public" / "data"

NE_10M_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_10m_admin_1_states_provinces.geojson"
)

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


def fetch(url: str) -> bytes:
    print(f"Fetching {url} ...")
    return urllib.request.urlopen(url, timeout=120).read()


def main() -> None:
    geo = json.loads(fetch(NE_10M_URL).decode("utf-8"))
    features = []

    seen_rus: set[str] = set()
    for feature in geo["features"]:
        props = feature["properties"]
        adm0 = props.get("adm0_a3")
        if adm0 == "RUS":
            name = props.get("name_ru") or props.get("name", "")
            if name in seen_rus:
                continue
            seen_rus.add(name)
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "name": props.get("name_ru") or props.get("name", ""),
                        "name_en": props.get("name_en") or props.get("name", ""),
                        "code": props.get("iso_3166_2", ""),
                    },
                    "geometry": feature["geometry"],
                }
            )
            continue
        if adm0 == "UKR":
            meta = DNR_LNR_REGIONS.get(props.get("name"))
            if meta:
                features.append(
                    {
                        "type": "Feature",
                        "properties": meta,
                        "geometry": feature["geometry"],
                    }
                )

    fix_region_borders(features)
    regions = {"type": "FeatureCollection", "features": features}
    (DATA / "regions.geojson").write_text(
        json.dumps(regions, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Wrote {len(features)} regions to {DATA / 'regions.geojson'}")


if __name__ == "__main__":
    main()
