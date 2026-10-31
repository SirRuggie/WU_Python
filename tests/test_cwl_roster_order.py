from copy import deepcopy
from utils.cwl_roster_order import ordered_roster_clans


def test_lazy_trailing_numbers_descending_then_unnumbered_alphabetical():
    names = ['Zulu', 'W. U. Lazy.9', 'W. U. Lazy.128', 'Alpha', 'W. U. Lazy. 12', 'Clan 999', 'W. U. Lazy.12x']
    clans = [{'name': name, 'pool': 'lazy', 'tag': str(i)} for i, name in enumerate(names)]
    before = deepcopy(clans)
    assert [c['name'] for c in ordered_roster_clans(clans)] == [
        'W. U. Lazy.128', 'W. U. Lazy. 12', 'W. U. Lazy.9',
        'Alpha', 'Clan 999', 'W. U. Lazy.12x', 'Zulu',
    ]
    assert clans == before


def test_main_capacity_groups_and_empty_groups():
    clans = [{'name': name, 'pool': 'main', 'capacity': capacity} for name, capacity in [
        ('Alpha fifteen', 15), ('Zulu thirty', 30), ('Alpha thirty', 30),
        ('Zulu fifteen', 15), ('Alpha unknown', None), ('Beta other', 50),
    ]]
    assert [c['name'] for c in ordered_roster_clans(clans)] == [
        'Alpha thirty', 'Zulu thirty', 'Alpha fifteen', 'Zulu fifteen', 'Alpha unknown', 'Beta other',
    ]
    for capacity in (None, 15, 30):
        group = [c for c in clans if c['capacity'] == capacity]
        assert ordered_roster_clans(group) == sorted(group, key=lambda c: c['name'])
    assert ordered_roster_clans([]) == []


def test_equal_names_have_stable_tag_tiebreaker_and_main_precedes_lazy():
    clans = [dict(name='Same', tag=tag, pool=pool) for tag, pool in [('#Z', 'lazy'), ('#B', 'main'), ('#A', 'main')]]
    assert [c['tag'] for c in ordered_roster_clans(clans)] == ['#A', '#B', '#Z']


def test_image_list_uses_publication_capacity_and_shared_order(monkeypatch):
    import asyncio
    import json
    from cwl_web import roster_images, roster_image_posts
    metadata = [
        {'tag': '#SMALL', 'name': 'Alpha', 'pool': 'main', 'capacity': 15},
        {'tag': '#LARGE', 'name': 'Zulu', 'pool': 'main', 'capacity': 30},
    ]
    publication = ({'label': 'November'}, {'version': 3, 'clans_json': json.dumps(metadata)}, [
        {'assigned_clan_tag': c['tag'], 'assigned_clan_name': c['name'], 'pool': c['pool']}
        for c in metadata
    ])
    season, pub, groups = roster_image_posts.groups_for(publication)
    assert groups['#LARGE']['capacity'] == 30
    monkeypatch.setattr(roster_images, 'snapshot', lambda request: (season, pub, groups))
    response = asyncio.run(roster_images.listing(None))
    assert [c['tag'] for c in json.loads(response.body)['clans']] == ['#LARGE', '#SMALL']
