"""Short, mention-free messages accompanying a published CWL roster."""
import re
from urllib.parse import quote
from utils.dashboard_urls import ASSIGNMENTS_URL


def clan_name(value: str) -> str:
    # Names are external text. Neutralize mention syntax and Markdown delimiters.
    value = ' '.join(str(value).split())[:120].replace('@', '@\u200b')
    return re.sub(r'([\\`*_~|<>\[\]])', r'\\\1', value)


def link_button(label: str, url: str) -> list[dict]:
    return [{'type': 1, 'components': [{'type': 2, 'style': 5, 'label': label, 'url': url}]}]


def clan_image_message(name: str, tag: str, *, test: bool = False) -> dict:
    return {
        'content': ('TEST · ' if test else '') + f'**{clan_name(name)}**',
        'allowed_mentions': {'parse': []}, 'attachments': [],
        'components': link_button('Open clan',
            f'https://link.clashofclans.com/en?action=OpenClanProfile&tag={quote(tag, safe="")}'),
    }


def closing_message(*, test: bool = False) -> dict:
    return {
        'content': ('TEST · ' if test else '') + "Can't find your name? Check My assignments.",
        'allowed_mentions': {'parse': []},
        'components': link_button('My assignments', ASSIGNMENTS_URL),
    }
