#!/usr/bin/env python3
"""Merge missing region features from seed into the persistent regions file."""
import json
import os
from pathlib import Path

REGIONS_PATH = Path(os.environ.get("REGIONS_PATH", "/data/regions.geojson"))
SEED_PATH = Path(os.environ.get("SEED_REGIONS_PATH", "/seed/regions.geojson"))


def main() -> None:
    if not SEED_PATH.exists():
        return

    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))

    if not REGIONS_PATH.exists():
        REGIONS_PATH.write_text(
            json.dumps(seed, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Initialized {REGIONS_PATH} with {len(seed['features'])} regions")
        return

    data = json.loads(REGIONS_PATH.read_text(encoding="utf-8"))
    existing = {f["properties"]["name"] for f in data.get("features", [])}
    added = 0

    for feature in seed.get("features", []):
        name = feature["properties"]["name"]
        if name in existing:
            continue
        data.setdefault("features", []).append(feature)
        existing.add(name)
        added += 1

    if not added:
        return

    tmp = REGIONS_PATH.with_name(f"{REGIONS_PATH.name}.merge.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(REGIONS_PATH)
    print(f"Merged {added} regions into {REGIONS_PATH}")


if __name__ == "__main__":
    main()
