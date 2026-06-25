#!/usr/bin/env python3
"""Keep persistent regions.geojson in sync with the image seed."""
import hashlib
import json
import os
from pathlib import Path

REGIONS_PATH = Path(os.environ.get("REGIONS_PATH", "/data/regions.geojson"))
SEED_PATH = Path(os.environ.get("SEED_REGIONS_PATH", "/seed/regions.geojson"))


def main() -> None:
    if not SEED_PATH.exists():
        return

    seed_text = SEED_PATH.read_text(encoding="utf-8")
    seed_hash = hashlib.sha256(seed_text.encode()).hexdigest()

    if REGIONS_PATH.exists():
        current_hash = hashlib.sha256(
            REGIONS_PATH.read_text(encoding="utf-8").encode()
        ).hexdigest()
        if current_hash == seed_hash:
            return

    REGIONS_PATH.write_text(seed_text, encoding="utf-8")
    seed = json.loads(seed_text)
    print(f"Synced {len(seed.get('features', []))} regions into {REGIONS_PATH}")


if __name__ == "__main__":
    main()
