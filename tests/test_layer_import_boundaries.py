"""Every tracked layer import is scanned, including imports deferred in functions.

Legacy entries are exact source/target edges. A repaired edge must be removed;
new entries require explicit review, never a package-level or wildcard exception.
"""
import ast
from importlib.util import resolve_name
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).parents[1]
# Existing violations only; subsequent Part L batches must shrink this list.
LEGACY_EDGES = frozenset({
    ('cwl_web/manage_content.py', 'extensions.commands.content'),
    ('cwl_web/manage_delivery.py', 'extensions.commands.content'),
    ('cwl_web/manage_tickets.py', 'extensions.commands.tickets.testing_service'),
    ('cwl_web/server_management.py', 'extensions.commands.tickets.testing_service'),
    ('cwl_web/staff_overview.py', 'extensions.commands.tickets.perms.is_recruiter'),
    ('cwl_web/staff_overview.py', 'extensions.commands.tickets.store.RUNTIME_FILTER'),
    ('cwl_web/ticket_browser.py', 'extensions.commands.tickets.account_sync'),
    ('cwl_web/ticket_browser.py', 'extensions.commands.tickets.flag_store'),
    ('cwl_web/ticket_browser.py', 'extensions.commands.tickets.perms.is_recruiter'),
    ('cwl_web/ticket_browser.py', 'extensions.commands.tickets.store.BROWSE_PROJECTION'),
    ('cwl_web/ticket_browser.py', 'extensions.commands.tickets.store.RUNTIME_FILTER'),
    ('extensions/commands/strikes.py', 'cwl_web.providers.LiveProviders'),
    ('extensions/commands/strikes.py', 'cwl_web.providers.ProviderUnavailable'),
    ('extensions/commands/tickets/settings.py', 'cwl_web.change_history.begin'),
    ('extensions/commands/tickets/settings.py', 'cwl_web.change_history.finish'),
    ('extensions/commands/tickets/settings.py', 'cwl_web.manage_content.GUILD_ID'),
    ('extensions/commands/tickets/settings.py', 'cwl_web.manage_tickets.history_values'),
    ('utils/cwl_campaign.py', 'extensions.tasks.cwl_reminder'),
    ('utils/cwl_publishing.py', 'extensions.commands.content.canonical_media_url'),
    ('utils/cwl_publishing.py', 'extensions.commands.content.discord_attachment_id'),
    ('utils/cwl_publishing.py', 'extensions.commands.content.media_galleries'),
    ('utils/cwl_publishing.py', 'extensions.commands.content.media_url'),
    ('utils/dashboard_native_history.py', 'cwl_web.change_history.begin'),
    ('utils/dashboard_native_history.py', 'cwl_web.change_history.fields'),
    ('utils/dashboard_native_history.py', 'cwl_web.change_history.finish'),
    ('utils/dashboard_native_history.py', 'cwl_web.manage_content.GUILD_ID'),
    ('utils/dashboard_native_history.py', 'cwl_web.manage_content.descriptor'),
    ('utils/dashboard_native_history.py', 'cwl_web.manage_content.load'),
    ('utils/dashboard_native_history.py', 'cwl_web.manage_content.schema'),
    ('utils/fwa_war_content.py', 'extensions.commands.fwa.message_templates.FOOTER_IMAGES'),
    ('utils/fwa_war_content.py', 'extensions.commands.fwa.message_templates.WAR_COLORS'),
    ('utils/fwa_war_content.py', 'extensions.commands.fwa.message_templates.WarCopyTexts'),
    ('utils/fwa_war_content.py', 'extensions.commands.fwa.message_templates.WarMessageTemplates'),
    ('utils/fwa_war_content.py', 'extensions.commands.fwa.message_templates.sanitize_opponent_for_header'),
    ('utils/manage_web_worker.py', 'cwl_web.change_history.begin'),
    ('utils/manage_web_worker.py', 'cwl_web.change_history.finish'),
    ('utils/manage_web_worker.py', 'cwl_web.manage_clans.audit'),
    ('utils/manage_web_worker.py', 'cwl_web.manage_content.fingerprint'),
    ('utils/manage_web_worker.py', 'cwl_web.manage_delivery.publish'),
    ('utils/manage_web_worker.py', 'cwl_web.manage_tickets.history_values'),
    ('utils/manage_web_worker.py', 'cwl_web.manage_tickets.validated_settings'),
    ('utils/manage_web_worker.py', 'extensions.commands.fwa.lazy_cwl_service'),
    ('utils/manage_web_worker.py', 'extensions.commands.tickets.console'),
    ('utils/manage_web_worker.py', 'extensions.commands.tickets.settings'),
    ('utils/manage_web_worker.py', 'extensions.commands.tickets.testing_service'),
    ('utils/manage_web_worker.py', 'extensions.member_role_dashboard.apply'),
    ('utils/manage_web_worker.py', 'extensions.member_role_dashboard.request_context'),
    ('utils/manage_web_worker.py', 'extensions.tasks.band_monitor'),
    ('utils/manage_web_worker.py', 'extensions.tasks.band_sync_ical'),
    ('utils/manage_web_worker.py', 'extensions.tasks.fwa_points_monitor'),
    ('utils/manage_web_worker.py', 'extensions.warrior.profile_dashboard.apply'),
    ('utils/manage_web_worker.py', 'extensions.warrior.profile_dashboard.request_context'),
    ('utils/ticket_testing_context.py', 'extensions.commands.tickets.testing_service'),
    ('utils/ticket_testing_control.py', 'extensions.commands.tickets.perms'),
    ('utils/ticket_testing_control.py', 'extensions.commands.tickets.testing_service'),
    ('utils/ticket_testing_control.py', 'extensions.commands.tickets.thread_service'),
})


def import_edges(name, source):
    package = name.removesuffix('.py').replace('/', '.')
    if not name.endswith('/__init__.py'):
        package = package.rsplit('.', 1)[0]
    else:
        package = package.removesuffix('.__init__')
    for node in ast.walk(ast.parse(source, filename=name)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield name, alias.name
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ''
            if node.level:
                base = resolve_name('.' * node.level + base, package)
            for alias in node.names:
                yield name, base + '.' + alias.name


def forbidden(edge):
    name, target = edge
    def within(module):
        return target == module or target.startswith(module + '.')
    return ((name.startswith('utils/') and (within('cwl_web') or within('extensions')))
            or (name.startswith('cwl_web/') and within('extensions.commands'))
            or (name.startswith('extensions/') and within('cwl_web')))


def violations(sources):
    return {edge for name, source in sources.items()
            for edge in import_edges(name, source) if forbidden(edge)}


def tracked_sources():
    names = subprocess.check_output(
        ['git', 'ls-files', '-z', '--', 'utils', 'cwl_web', 'extensions'],
        cwd=ROOT, text=True,
    ).split('\0')
    return {name: (ROOT / name).read_text(encoding='utf-8')
            for name in names if name.endswith('.py')}


def test_tracked_layer_edges_match_shrink_only_legacy_allowlist():
    actual = violations(tracked_sources())
    assert actual == LEGACY_EDGES, {
        'new_forbidden_edges': sorted(actual - LEGACY_EDGES),
        'fixed_edges_remove_from_allowlist': sorted(LEGACY_EDGES - actual),
    }


@pytest.mark.parametrize('name,source,target', [
    ('utils/new.py', 'import extensions.new_service', 'extensions.new_service'),
    ('utils/deep/new.py', 'def run():\n from cwl_web import app', 'cwl_web.app'),
    ('utils/deep/new.py', 'def run():\n from extensions.commands.recruit import perms', 'extensions.commands.recruit.perms'),
    ('cwl_web/deep/new.py', 'async def run():\n from extensions.commands.recruit.perms import guild_permissions', 'extensions.commands.recruit.perms.guild_permissions'),
    ('cwl_web/new.py', 'from extensions.commands import new_service', 'extensions.commands.new_service'),
    ('extensions/deep/new.py', 'def run():\n import cwl_web.app as dashboard', 'cwl_web.app'),
    ('extensions/new.py', 'from cwl_web import app', 'cwl_web.app'),
])
def test_new_absolute_and_deferred_edges_are_rejected(name, source, target):
    edge = (name, target)
    assert violations({name: source}) == {edge}
    assert edge not in LEGACY_EDGES


def test_relative_imports_are_resolved_before_layer_check():
    assert set(import_edges('utils/deep/new.py', 'from .. import role_permissions')) == {
        ('utils/deep/new.py', 'utils.role_permissions')}
    with pytest.raises(ImportError):
        list(import_edges('utils/new.py', 'from ..extensions import service'))


def test_from_import_alias_targets_are_individual_edges():
    source = 'from extensions.commands.recruit import perms as permissions, questions'
    assert violations({'utils/new.py': source}) == {
        ('utils/new.py', 'extensions.commands.recruit.perms'),
        ('utils/new.py', 'extensions.commands.recruit.questions')}


def test_allowed_layer_directions_remain_unrestricted():
    assert violations({
        'extensions/deep/new.py': 'from utils.role_permissions import guild_permissions',
        'cwl_web/new.py': 'from utils import role_permissions',
        'utils/deep/new.py': 'from ..role_permissions import guild_permissions',
    }) == set()
