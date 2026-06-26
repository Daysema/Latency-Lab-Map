"""Normalize Natural Earth admin-1 names for Russian federal subjects."""

REGION_BY_CODE = {
    "RU-ALT": {
        "name": "Алтайский край",
        "name_en": "Altai Krai",
    },
}


def region_properties(props: dict) -> dict | None:
    code = props.get("iso_3166_2", "")
    override = REGION_BY_CODE.get(code)
    if override:
        return {
            "name": override["name"],
            "name_en": override["name_en"],
            "code": code,
        }

    name = props.get("name_ru") or props.get("name", "")
    if not name:
        return None

    return {
        "name": name,
        "name_en": props.get("name_en") or props.get("name", ""),
        "code": code,
    }


def prepare_russian_regions(geo: dict) -> list[dict]:
    features = []
    seen_codes: set[str] = set()

    for feature in geo["features"]:
        props = feature["properties"]
        if props.get("adm0_a3") != "RUS":
            continue

        code = props.get("iso_3166_2", "")
        if code in seen_codes:
            continue

        region = region_properties(props)
        if not region:
            continue

        seen_codes.add(code)
        features.append(
            {
                "type": "Feature",
                "properties": region,
                "geometry": feature["geometry"],
            }
        )

    return features
