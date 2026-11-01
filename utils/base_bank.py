"""Public read-only FWA base projection. Staff configuration is never returned."""

from urllib.parse import urlsplit, parse_qs

FWA_TH_LEVELS = [
    "th18_new",
    "th18",
    "th17_new",
    "th17",
    "th16_new",
    "th16",
    "th15",
    "th14",
    "th13",
    "th12",
    "th11",
    "th10",
    "th9",
]
PUBLIC_FIELDS = (
    "fwa_base_links",
    "war_base_images",
    "base_information",
    "base_upgrade_notes",
)


def https_url(value, *, clash=False):
    if (
        not isinstance(value, str)
        or len(value) > 4096
        or any(ord(c) <= 32 for c in value)
    ):
        return None
    try:
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.port
            or url.fragment
        ):
            return None
        if clash and (
            url.hostname != "link.clashofclans.com"
            or parse_qs(url.query).get("action") != ["OpenLayout"]
            or not parse_qs(url.query).get("id")
        ):
            return None
    except ValueError:
        return None
    return value


def public_bases(document):
    rows, details = [], {}
    document = document if isinstance(document, dict) else {}
    fields = {
        key: document.get(key) if isinstance(document.get(key), dict) else {}
        for key in PUBLIC_FIELDS
    }
    for key in FWA_TH_LEVELS:
        info = {
            name: (
                fields[name].get(key)[:4000]
                if isinstance(fields[name].get(key), str)
                else ""
            )
            for name in ("base_information", "base_upgrade_notes")
        }
        info = {name: text if text.strip() else "" for name, text in info.items()}
        link = https_url(fields["fwa_base_links"].get(key), clash=True)
        image = https_url(fields["war_base_images"].get(key))
        if not link and not image:
            continue
        rows.append(
            dict(
                key=key,
                town_hall=int(key[2:].split("_")[0]),
                variant="non-merged" if key.endswith("_new") else "merged",
                link=link,
                war_base_image=image,
                has_details=any(info.values()),
            )
        )
        details[key] = info
    rows.sort(key=lambda row: (-row["town_hall"], row["variant"] != "merged"))
    return rows, details


async def read_base_bank(mongo):
    document = await mongo.fwa_data.find_one(
        {"_id": "fwa_config"}, {**{field: 1 for field in PUBLIC_FIELDS}, "_id": 0}
    )
    return public_bases(document)
