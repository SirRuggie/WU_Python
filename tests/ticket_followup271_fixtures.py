"""In-memory canonical notification owner, without creation/component TTL state."""
from copy import deepcopy
from types import SimpleNamespace
from tests.test_cwl_dashboard_integration import MemoryCollection


def opening_mongo(ticket, *, new_notification=False):
    row = deepcopy(ticket)
    row.setdefault("runtime", "thread_v2")
    if new_notification:
        row['opening_member_notification'] = {
            'state':'pending','user_id':row['user_id'],'channel_id':row['location']['id'],
        }
    return SimpleNamespace(tickets=MemoryCollection({row['_id']:row}))
