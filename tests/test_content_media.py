"""Pure gallery/media preservation contracts; no transport or storage."""
from types import SimpleNamespace as NS

import hikari
import pytest

from utils import content_media as media


def gallery(*urls, children=()):
    return NS(type=hikari.ComponentType.MEDIA_GALLERY,
              items=[NS(media=NS(url=url)) for url in urls], components=children)


def test_extension_reexports_single_pure_owner():
    from extensions.commands import content
    for name in ('media_galleries', 'media_url', 'canonical_media_url',
                 'discord_attachment_id', 'media_snapshot'):
        assert getattr(content, name) is getattr(media, name)
        assert getattr(media, name).__module__ == 'utils.content_media'


def test_nested_gallery_traversal_keeps_preorder_and_does_not_mutate():
    first = gallery('https://img.example/first')
    nested = gallery('https://img.example/nested')
    outer_gallery = gallery('https://img.example/outer', children=[nested])
    last = gallery('https://img.example/last')
    card = NS(type=hikari.ComponentType.CONTAINER, components=[first, outer_gallery])
    nodes = [NS(type=hikari.ComponentType.TEXT_DISPLAY), card, last]
    assert media.media_galleries(nodes) == [first, outer_gallery, nested, last]
    assert media.media_snapshot(nodes) == [
        'https://img.example/first', 'https://img.example/outer',
        'https://img.example/nested', 'https://img.example/last',
    ]
    assert card.components == [first, outer_gallery]
    assert outer_gallery.components == [nested]
    assert media.media_galleries([]) == media.media_snapshot([]) == []


@pytest.mark.parametrize('item,expected', [
    (NS(), ''), (NS(media=None), ''), (NS(media='attachment://file.png'), 'attachment://file.png'),
    (NS(media=NS(url='https://img.example/a')), 'https://img.example/a'),
    (NS(media=NS(url=None)), ''), (NS(media=NS(url=123)), '123'),
])
def test_media_url_preserves_original_member_shapes(item, expected):
    assert media.media_url(item) == expected


@pytest.mark.parametrize('urls', [(), ('a', 'b')])
def test_snapshot_rejects_empty_or_multi_item_gallery_exactly(urls):
    with pytest.raises(ValueError, match=r'^The content dashboard does not support the image layout of that post\.$'):
        media.media_snapshot([gallery(*urls)])


@pytest.mark.parametrize('url', ['', None])
def test_snapshot_rejects_empty_media_slot_exactly(url):
    with pytest.raises(ValueError, match=r'^This post has an empty media slot\.$'):
        media.media_snapshot([gallery(url)])


@pytest.mark.parametrize('host', ['cdn.discordapp.com', 'media.discordapp.net', 'cdn.discordapp.net'])
def test_discord_attachment_signature_only_removed_with_order_and_blanks(host):
    url = f'https://{host}/attachments/10/20/a.png?width=1&ex=x&blank=&is=y&width=2&hm=z&EX=keep#frag'
    expected = f'https://{host}/attachments/10/20/a.png?width=1&blank=&width=2&EX=keep#frag'
    assert media.canonical_media_url(url) == expected
    assert media.media_snapshot([gallery(url)]) == [expected]
    assert media.discord_attachment_id(url) == '20'


@pytest.mark.parametrize('url', [
    'https://img.example/attachments/10/20/a.png?ex=x&is=y&hm=z',
    'https://cdn.discordapp.com/icons/10/a.png?ex=x&is=y&hm=z',
    'https://cdn.discordapp.com/attachments-else/10/20/a.png?ex=x',
    'https://cdn.discordapp.com.evil.example/attachments/10/20/a.png?ex=x',
    'https://media.discordapp.net.evil.example/attachments/10/20/a.png?hm=z',
    'attachment://a.png?hm=z',
])
def test_non_attachment_or_non_discord_url_is_unchanged(url):
    assert media.canonical_media_url(url) == url
    assert media.discord_attachment_id(url) is None


@pytest.mark.parametrize('url,expected', [
    ('https://cdn.discordapp.com/attachments/channel/00020/a.png', '00020'),
    ('https://media.discordapp.net/attachments/10/20/a.png/extra', '20'),
    ('https://cdn.discordapp.net/attachments/10/not-an-id/a.png', None),
    ('https://cdn.discordapp.com/attachments/10/20', None),
    ('https://cdn.discordapp.com/other/10/20/a.png', None),
])
def test_attachment_id_preserves_original_path_rules(url, expected):
    assert media.discord_attachment_id(url) == expected
