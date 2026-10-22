"""Bounded diagnostic receipts. Never store request bodies, URLs, or exception text."""
import time

DOCUMENT = 'dashboard-issues-v1'
LIMIT = 500


class IssueRepository:
    def __init__(self, collection):
        self.collection = collection

    async def append(self, issue):
        await self.collection.update_one(
            {'_id': DOCUMENT},
            {'$push': {'items': {'$each': [issue], '$slice': -LIMIT}}}, upsert=True)

    async def recent(self):
        document = await self.collection.find_one({'_id': DOCUMENT}) or {}
        cutoff = time.time() - 30 * 86400
        return [item for item in reversed(document.get('items', [])) if item['at'] >= cutoff]
