"""Synthetic registry for calculator behavior, never an application default."""


def weight_registry(*, newest=18, guild_id=2):
    levels = {str(level): {'emoji': ''} for level in range(1, newest + 1)}
    for level in range(9, newest + 1):
        low, high = ((56000, 70000) if level == 9 else (71000, 90000) if level == 10
                     else (91000, 110000) if level == 11 else
                     (111000 + (level - 12) * 10000, 120000 + (level - 12) * 10000))
        levels[str(level)]['weight'] = {'min': low, 'max': high}
    return {'_id': str(guild_id), 'schema_version': 1, 'revision': 7,
            'lowest_fwa_town_hall': 12, 'levels': levels}


def install_snapshot(monkeypatch):
    from utils import town_halls
    from tools.migrate_town_halls import SEED_EMOJIS
    doc=weight_registry(newest=19)
    for level,markup in SEED_EMOJIS.items():
        if str(level) in doc['levels']:doc['levels'][str(level)]['emoji']=markup
    monkeypatch.setattr(town_halls,'_snapshot',doc)
    monkeypatch.setattr(town_halls,'_snapshot_guild',doc['_id'])
    return doc
