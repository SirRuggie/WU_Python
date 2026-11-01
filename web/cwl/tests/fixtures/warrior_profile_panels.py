"""Build sample panels from the real wizard for an approximate Discord preview."""

import json
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


def blocked(*args, **kwargs):
    raise RuntimeError("Preview forbids network")


socket.socket.connect = blocked
socket.getaddrinfo = blocked
from extensions.warrior.nickname_setup import render
from cwl_web.manage_content import serialize_components

data = {"_id": "fixture"}
base = {
    "nonce": "fixture",
    "name": "Example Hero",
    "zone_id": "gmt-5",
    "country": "US",
    "accounts": [
        {"tag": "#PYY", "name": "Example Hero", "townHallLevel": 18},
        {"tag": "#PQQ", "name": "Second Main", "townHallLevel": 18},
    ],
}
scenarios = {
    "Choose an account": dict(base, step="name"),
    "No links": dict(base, step="name", accounts=[]),
    "Country": dict(base, step="country"),
    "Time zone": dict(base, step="zone"),
    "Australia zones": dict(base, step="zone", country="AU"),
    "United States zones": dict(base, step="zone", country="US"),
    "All zones": dict(base, step="zone", country="AU", all_zones=True),
    "Preview": dict(base, step="preview"),
    "Shorten a name": dict(
        base, step="preview", name="A very long example name that needs shortening"
    ),
    "Partial upstream data": dict(base, step="name", unavailable=True),
}
print(
    json.dumps(
        {
            title: serialize_components(render(data, state), "warrior-fixture")
            for title, state in scenarios.items()
        }
    )
)
