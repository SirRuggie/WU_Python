"""Shared destination settings for native and web return reminders."""
from .lazy_cwl_store import normalize_section

DOCUMENT_ID = 'cwl-return-destinations'
DEFAULT_CHANNELS = {'MAIN': 1555939498016374985, 'FWA': 1424256751913668770}
FIELDS = {'MAIN': 'main_channel_id', 'FWA': 'fwa_channel_id'}


async def load(mongo):
    # Legacy test adapters may not expose bot_config; real clients always do.
    collection = getattr(mongo, 'bot_config', None)
    return (await collection.find_one({'_id': DOCUMENT_ID}) or {}) if collection is not None else {}


def channels(row):
    return {section: int(row.get(field) or DEFAULT_CHANNELS[section]) for section, field in FIELDS.items()}


async def destination(mongo, section):
    section = normalize_section(section)
    return channels(await load(mongo))[section]
