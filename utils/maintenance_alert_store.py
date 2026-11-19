"""Single majority-write owner of the observed Clash maintenance alert window."""
from datetime import timedelta
from uuid import uuid4

from pymongo.errors import DuplicateKeyError
from pymongo.write_concern import WriteConcern

from utils.mongo_routes import collection_from
from utils.constants import LOG_CHANNEL_ID
from utils.war_reminder_health import timestamp


class MaintenanceAlertStore:
    CLOSED_FIELDS = ('message_id', 'channel_id', 'started_at', 'ended_at', 'final_render')

    def __init__(self, db):
        self.rows = collection_from(
            db.bot_config, 'maintenance_alert', write_concern=WriteConcern(w='majority')
        )

    async def get(self):
        return await self.rows.find_one({'_id': 'clash'})

    async def change(self, before, **values):
        result = await self.rows.update_one(
            {'_id': before.get('_id', 'clash'), 'revision': before['revision'],
             'started_at': before['started_at'], 'message_id': before.get('message_id'),
             'channel_id': before['channel_id'], 'state': before['state']},
            {'$set': values, '$inc': {'revision': 1}},
        )
        return bool(result.matched_count)

    @staticmethod
    def window_id(row):
        """Stable key from the existing first-observed, BSON-ms window identity."""
        started = timestamp(row.get('started_at'))
        if started is None:
            raise ValueError('Maintenance window identity is unavailable')
        return 'clash:' + started.isoformat(timespec='milliseconds')

    @classmethod
    def closed_identity(cls, row):
        if (row.get('_id') != cls.window_id(row)
                or str(row.get('channel_id')) != str(LOG_CHANNEL_ID)
                or timestamp(row.get('ended_at')) is None
                or not isinstance(row.get('final_render'), str)):
            raise ValueError('Closed maintenance receipt identity is invalid')
        return {key: timestamp(row[key]) if key in ('started_at', 'ended_at') else row.get(key)
                for key in cls.CLOSED_FIELDS}

    async def preserve_closed(self, row):
        """Commit immutable old-message authority BEFORE replacing the singleton.

        Transfer a known dirty event once, then clear that singleton flag by CAS.
        A racing callback changes its revision and forces the caller to reread.
        """
        receipt = dict(_id=self.window_id(row), message_id=row.get('message_id'),
                       channel_id=row['channel_id'], started_at=row['started_at'],
                       ended_at=row.get('ended_at'), final_render=row.get('final_render'),
                       revision=1, state=('unconfirmed' if not row.get('message_id') else
                                          'dirty' if row.get('needs_red_edit') else 'reconciled'))
        expected = self.closed_identity(receipt)
        try:
            await self.rows.insert_one(receipt)
        except DuplicateKeyError:
            existing = await self.rows.find_one({'_id': receipt['_id']})
            if not existing:
                raise ValueError('Closed maintenance receipt does not match its window')
            actual = self.closed_identity(existing)
            if actual != expected:
                # An archive insert may have copied None just before the known
                # POST return attached to the singleton. Its revision forces
                # replacement to reread; carry that durable fill-once fact on.
                if (actual['message_id'] is None and existing['state'] == 'unconfirmed'
                        and expected['message_id'] is not None
                        and {k: v for k, v in actual.items() if k != 'message_id'}
                        == {k: v for k, v in expected.items() if k != 'message_id'}):
                    if not await self.change(existing, message_id=expected['message_id'],
                                              state=receipt['state']):
                        return None
                    existing = {**existing, 'message_id': expected['message_id'],
                                'state': receipt['state'], 'revision': existing['revision'] + 1}
                else:
                    raise ValueError('Closed maintenance receipt does not match its window')
            if row.get('needs_red_edit'):
                await self.invalidate_closed(existing)
        if row.get('needs_red_edit'):
            if not await self.change(row, needs_red_edit=False):
                return None
            return {**row, 'revision': row['revision'] + 1, 'needs_red_edit': False}
        return row

    async def dirty_closed(self):
        return await self.rows.find({'state': 'dirty'}).to_list(length=None)

    async def invalidate_closed(self, before):
        expected = self.closed_identity(before)
        if not before.get('message_id'):
            return False  # An uncertain POST with no known ID is never reposted.
        while True:
            current = await self.rows.find_one({'_id': before['_id']})
            if not current or self.closed_identity(current) != expected:
                return False
            if await self.change(current, state='dirty'):
                return True

    async def observe(self, started, now, channel_id):
        """The winning uncertain intent is durable BEFORE the single post attempt."""
        started, now = timestamp(started), timestamp(now)
        if started is None or now is None:
            raise ValueError('Actual maintenance observations required')
        started = started.replace(microsecond=started.microsecond // 1000 * 1000)
        now = now.replace(microsecond=now.microsecond // 1000 * 1000)
        while True:
            row = await self.get()
            if row:
                if str(row.get('channel_id')) != str(channel_id):
                    raise ValueError('Maintenance alert destination does not match configuration')
                seen = timestamp(row.get('last_maintenance_at'))
                # Re-observing stale process memory is not another 503. Only a
                # newer actual observation may cancel a clear timer/open a window.
                boundary = timestamp(row.get('clear_since')) if row['state'] == 'closed' else seen
                if boundary is not None and now <= boundary:
                    return row, False
            if row and row['state'] != 'closed':
                seen = timestamp(row.get('last_maintenance_at'))
                values = dict(last_maintenance_at=max(seen, now) if seen else now,
                              clear_since=None, edit_claim=None, edit_until=None)
                if row['state'] == 'closing':
                    values.update(state='open', needs_red_edit=True)
                if await self.change(row, **values):
                    return await self.get(), False
                continue
            values = dict(message_id=None, channel_id=str(channel_id), started_at=started,
                          last_maintenance_at=now, clear_since=None, state='uncertain',
                          edit_claim=None, edit_until=None, needs_red_edit=False,
                          ended_at=None, final_render=None)
            if row:
                row = await self.preserve_closed(row)
                if row is None:
                    continue
                if await self.change(row, **values):
                    return {**row, **values, 'revision': row['revision'] + 1}, True
            else:
                try:
                    intent = {'_id': 'clash', 'revision': 1, **values}
                    await self.rows.insert_one(intent)
                    return intent, True
                except DuplicateKeyError:
                    continue

    @staticmethod
    def post_intent(row):
        return (row.get('_id') == 'clash' and row.get('state') == 'uncertain'
                and row.get('message_id') is None
                and type(row.get('revision')) is int and row['revision'] > 0
                and str(row.get('channel_id')) == str(LOG_CHANNEL_ID)
                and timestamp(row.get('started_at')) is not None)

    @staticmethod
    def same_window(left, right):
        return (str(left.get('channel_id')) == str(LOG_CHANNEL_ID)
                and str(right.get('channel_id')) == str(LOG_CHANNEL_ID)
                and timestamp(left.get('started_at')) == timestamp(right.get('started_at')))

    async def can_post(self, intent):
        """Recheck eligibility, never substitute this read for the winning intent."""
        if not self.post_intent(intent):
            return False
        current = await self.get()
        return bool(current and self.same_window(intent, current)
                    and current['state'] == 'uncertain' and current.get('message_id') is None)

    async def posted(self, intent, message_id):
        """Record a known return once on its own singleton or closed receipt."""
        if (not self.post_intent(intent) or isinstance(message_id, bool)
                or not str(message_id).isdigit() or int(message_id) <= 0):
            return False
        message_id = str(message_id)
        while True:
            current = await self.get()
            if current and self.same_window(intent, current):
                known = current.get('message_id')
                if known is not None:
                    return known == message_id
                if current['state'] not in ('uncertain', 'open', 'closing', 'closed'):
                    return False
                values = dict(message_id=message_id)
                if current['state'] == 'uncertain':
                    values['state'] = 'open'
                elif current['state'] == 'closing':
                    values.update(state='open', needs_red_edit=True, edit_claim=None, edit_until=None)
                elif current['state'] == 'closed':
                    values['needs_red_edit'] = True
                if await self.change(current, **values):
                    return True
                continue
            receipt = await self.rows.find_one({'_id': self.window_id(intent)})
            if not receipt or not self.same_window(intent, receipt):
                return False
            self.closed_identity(receipt)
            known = receipt.get('message_id')
            if known is not None:
                return known == message_id
            if receipt['state'] != 'unconfirmed':
                return False
            if await self.change(receipt, message_id=message_id, state='dirty'):
                return True

    async def claim_edit(self, row, now, *, close=False):
        """Persist dirty intent before REST; retain its exact acknowledgement version."""
        if str(row.get('channel_id')) != str(LOG_CHANNEL_ID):
            raise ValueError('Maintenance alert destination does not match configuration')
        if row.get('_id', 'clash') != 'clash':
            self.closed_identity(row)
            if row['state'] != 'dirty':
                return None
            if await self.change(row, state='dirty'):
                return {**row, 'revision': row['revision'] + 1, 'edit_claim': uuid4().hex}
            return None
        until = timestamp(row.get('edit_until'))
        if until and now < until:
            return None
        values = dict(state='closing' if close else row['state'],
                      edit_claim=uuid4().hex, edit_until=now + timedelta(seconds=90),
                      needs_red_edit=True)
        if await self.change(row, **values):
            return {**row, **values, 'revision': row['revision'] + 1}
        return None

    @classmethod
    def same_message(cls, left, right):
        return cls.same_window(left, right) and left.get('message_id') == right.get('message_id')

    async def invalidate_edit(self, intent, *, green_render=None):
        """A stale completion dirties only its retained, configured message/window."""
        while True:
            current = await self.get()
            if not current or not self.same_message(intent, current):
                receipt = await self.rows.find_one({'_id': self.window_id(intent)})
                if not receipt or not self.same_message(intent, receipt):
                    return False
                if green_render is not None and receipt.get('final_render') == green_render:
                    return False  # A known late GREEN did not spoil the stored GREEN.
                return await self.invalidate_closed(receipt)
            if (green_render is not None and current['state'] == 'closed'
                    and current.get('final_render') == green_render):
                return False
            if await self.change(current, needs_red_edit=True):
                return True

    async def finish_edit(self, intent, *, ended=None, final_render=None, success=True):
        """An old REST completion must never acknowledge a newer render intent."""
        if intent.get('_id', 'clash') != 'clash':
            self.closed_identity(intent)
            if not success:
                return await self.invalidate_closed(intent)
            result = await self.rows.update_one(
                {'_id': intent['_id'], 'revision': intent['revision'], 'state': 'dirty',
                 **{key: intent[key] for key in self.CLOSED_FIELDS}},
                {'$set': {'state': 'reconciled'}, '$inc': {'revision': 1}},
            )
            # Every receipt edit renders the identical immutable GREEN. A newer
            # RED invalidation must survive an older GREEN acknowledgement.
            return bool(result.matched_count)
        values = dict(needs_red_edit=not success, edit_claim=None, edit_until=None)
        if success and ended is not None:
            # Once closed, the hold is finished. Preserve the actual displayed
            # clear time in the existing field for restart/stale-red repair.
            if not isinstance(final_render, str):
                raise ValueError('Confirmed final maintenance render is required')
            values.update(state='closed', clear_since=timestamp(ended),
                          ended_at=timestamp(ended), final_render=final_render)
        elif intent['state'] == 'closing':
            values['state'] = 'open'
        result = await self.rows.update_one(
            {'_id': 'clash', 'revision': intent['revision'],
             'started_at': intent['started_at'], 'message_id': intent.get('message_id'),
             'channel_id': str(LOG_CHANNEL_ID), 'state': intent['state'],
             'edit_claim': intent['edit_claim']},
            {'$set': values, '$inc': {'revision': 1}},
        )
        if result.matched_count:
            return True
        await self.invalidate_edit(intent, green_render=final_render if success and ended is not None else None)
        return False
