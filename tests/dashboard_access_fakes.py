from copy import deepcopy
from types import SimpleNamespace
from pymongo.errors import DuplicateKeyError


class AccessCollection:
    def __init__(self):
        self.documents = {}
        self.fail = False

    async def find_one(self, query):
        return deepcopy(self.documents.get(query['_id']))

    async def insert_one(self, row):
        if self.fail:
            raise RuntimeError('Storage unavailable')
        if row['_id'] in self.documents:
            raise DuplicateKeyError('exists')
        self.documents[row['_id']] = deepcopy(row)

    async def replace_one(self, query, row):
        if self.fail:
            raise RuntimeError('Storage unavailable')
        existing = self.documents.get(query['_id'])
        if not existing or existing.get('revision') != query['revision']:
            return SimpleNamespace(matched_count=0)
        self.documents[row['_id']] = deepcopy(row)
        return SimpleNamespace(matched_count=1)
