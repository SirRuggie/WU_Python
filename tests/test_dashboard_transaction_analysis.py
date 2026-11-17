"""Mutation examples make receiver resolution part of the architecture contract."""
import textwrap

import pytest
from dashboard_transaction_analysis import IMAGE_STORE, PublisherAudit

SERVICE = '''
class RosterImageStore:
    def __init__(self, store):
        self.store = store
    def configure_test_channel(self):
        with self.store.tx() as db:
            db.execute('write')
'''


def audit(source, extra=None):
    return PublisherAudit({
        'utils.cwl_roster_image_store': textwrap.dedent(SERVICE),
        'sample': textwrap.dedent(source), **(extra or {}),
    })


@pytest.mark.parametrize('source', [
    '''
    from utils.cwl_roster_image_store import RosterImageStore
    async def save(app):
        RosterImageStore(app['store']).configure_test_channel()
    ''',
    '''
    from utils.cwl_roster_image_store import RosterImageStore as Images
    async def save(app):
        Images(app['store']).configure_test_channel()
    ''',
    '''
    import utils.cwl_roster_image_store as images
    async def save(app):
        images.RosterImageStore(app['store']).configure_test_channel()
    ''',
    '''
    from utils import cwl_roster_image_store as images
    async def save(app):
        images.RosterImageStore(app['store']).configure_test_channel()
    ''',
    '''
    from utils.cwl_roster_image_store import RosterImageStore
    async def save(app):
        constructor = RosterImageStore
        original = constructor(app['store'])
        alias = original
        alias.configure_test_channel()
    ''',
    '''
    from utils.cwl_roster_image_store import RosterImageStore
    async def save(app):
        storage = RosterImageStore(app['store'])
        bound = storage.configure_test_channel
        bound()
    ''',
    '''
    from utils.cwl_roster_image_store import RosterImageStore
    def factory(app):
        return RosterImageStore(app['store'])
    async def save(app):
        factory(app).configure_test_channel()
    ''',
    '''
    from utils.cwl_roster_image_store import RosterImageStore
    class Handler:
        def __init__(self, app):
            self.original = RosterImageStore(app['store'])
            self.alias = self.original
        async def save(self):
            self.alias.configure_test_channel()
    ''',
    '''
    from utils.cwl_roster_image_store import RosterImageStore
    async def helper(storage):
        storage.configure_test_channel()
    async def save(app):
        await helper(RosterImageStore(app['store']))
    ''',
    '''
    from utils.cwl_roster_image_store import RosterImageStore
    async def save(app):
        def write():
            RosterImageStore(app['store']).configure_test_channel()
        write()
    ''',
    '''
    from utils.cwl_roster_image_store import RosterImageStore
    async def save(app):
        (lambda: RosterImageStore(app['store']).configure_test_channel())()
    ''',
    '''
    from utils.cwl_roster_image_store import RosterImageStore
    async def save(app, unrelated):
        await unrelated.run_writer(lambda: RosterImageStore(app['store']).configure_test_channel())
    ''',
])
def test_forbidden_constructed_import_local_bound_factory_and_parameter_aliases(source):
    result = audit(source)
    assert result.violations(), result.inventory()


@pytest.mark.parametrize('source', [
    '''
    from utils.cwl_roster_image_store import RosterImageStore as Images
    async def save(app):
        await app['store'].run_writer(lambda: Images(app['store']).configure_test_channel())
    ''',
    '''
    from utils.cwl_roster_image_store import RosterImageStore
    async def save(app):
        storage = RosterImageStore(app['store'])
        def write():
            return storage.configure_test_channel()
        await app['store'].run_writer(write)
    ''',
    '''
    from utils.cwl_roster_image_store import RosterImageStore
    def tool(app):
        RosterImageStore(app['store']).configure_test_channel()
    ''',
    '''
    from utils.cwl_roster_image_store import RosterImageStore
    async def save(app):
        storage = RosterImageStore(app['store'])
        alias = storage.configure_test_channel
        await app['store'].run_writer(alias)
    ''',
])
def test_safe_offloaded_and_standalone_sync_variants(source):
    assert audit(source).violations() == []


def test_unrelated_async_mongo_configure_does_not_match_sqlite_publisher_name():
    result = audit('''
        from unrelated import DeclarationPingStore as Store
        async def save(db):
            storage = Store(db)
            await storage.configure()
    ''', {'unrelated': '''
class DeclarationPingStore:
    def __init__(self, db):
        self.db = db
    async def configure(self):
        pass
'''})
    assert result.violations() == []
    assert result.inventory() == []


def test_source_owner_discovers_new_publishing_method_without_method_allowlist():
    result = PublisherAudit({
        'utils.cwl_roster_image_store': textwrap.dedent(SERVICE) + '''
    def newly_added(self):
        with self.store.tx() as db:
            db.execute('write')
''',
        'sample': '''
from utils.cwl_roster_image_store import RosterImageStore as Images
async def save(app):
    Images(app['store']).newly_added()
''',
    })
    assert IMAGE_STORE + '.newly_added' in result.publishers
    assert result.violations()[0]['publishers'] == [IMAGE_STORE + '.newly_added']


@pytest.mark.parametrize('source', [
    '''
    from utils.cwl_roster_image_store import RosterImageStore
    Images = RosterImageStore
    async def save(app):
        Images(app['store']).configure_test_channel()
    ''',
    '''
    from utils.cwl_roster_image_store import RosterImageStore
    async def save(app):
        storage, ignored = RosterImageStore(app['store']), None
        storage.configure_test_channel()
    ''',
    '''
    from utils.cwl_roster_image_store import RosterImageStore
    def context(app):
        return None, RosterImageStore(app['store'])
    async def save(app):
        ignored, storage = context(app)
        storage.configure_test_channel()
    ''',
])
def test_global_constructor_and_tuple_factory_aliases_are_not_blind_spots(source):
    assert audit(source).violations()


def test_actual_handler_would_fail_if_writer_adapter_were_removed():
    import ast
    from pathlib import Path
    root = Path(__file__).parents[1]
    handler = ast.parse((root / 'cwl_web/announcement_settings.py').read_text())
    class RemoveWriter(ast.NodeTransformer):
        def visit_Await(self, node):
            call = node.value
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == 'run_writer':
                assert isinstance(call.args[0], ast.Lambda)
                return call.args[0].body
            return self.generic_visit(node)
    mutant = ast.unparse(ast.fix_missing_locations(RemoveWriter().visit(handler)))
    result = PublisherAudit({
        'utils.cwl_roster_image_store': (root / 'utils/cwl_roster_image_store.py').read_text(),
        'cwl_web.announcement_settings': mutant,
    })
    violations = result.violations()
    assert len(violations) == 1
    assert violations[0]['scope'] == 'cwl_web.announcement_settings.save'
    assert violations[0]['publishers'] == [IMAGE_STORE + '.configure_test_channel']


@pytest.mark.parametrize('writer', ["app['store'].run_writer", 'storage.store.run_writer'])
def test_async_mongo_method_cannot_be_given_to_a_sync_writer_even_by_same_name(writer):
    source = '''
        from unrelated import DeclarationPingStore as Store
        async def save(app, db):
            storage = Store(db)
            await WRITER(lambda: storage.claim())
    '''.replace('WRITER', writer)
    result = audit(source, {'unrelated': '''
class DeclarationPingStore:
    def __init__(self, db):
        self.db = db
    async def claim(self):
        pass
'''})
    assert result.violations()[0]['async_in_sync_writer'] == ['unrelated.DeclarationPingStore.claim']


def test_named_sync_callback_inventory_records_offload_without_hiding_direct_invocation():
    source = """
    from utils.cwl_roster_image_store import RosterImageStore
    async def save(app):
        storage = RosterImageStore(app['store'])
        def write():
            return storage.configure_test_channel()
        await app['store'].run_writer(write)
    """
    result = audit(source)
    assert result.violations() == []
    assert result.inventory()[0]['offloaded'] is True
    unsafe = source + "\n        write()\n"
    assert audit(unsafe).violations()
