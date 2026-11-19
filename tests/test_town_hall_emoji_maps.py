"""One registry emoji source; neither bot code nor components contain a map."""
import ast
from pathlib import Path
import re
import hikari
from utils import town_halls
from utils.emoji import emojis, town_hall_select_emoji
from town_halls_fixture import install_snapshot

ROOT=Path(__file__).resolve().parents[1]


def test_th19_uses_saved_th19a_and_components_use_an_id(monkeypatch):
    install_snapshot(monkeypatch)
    assert town_halls.town_hall_emoji(19)=='<:TH_19A:1571025137896005783>'
    option=hikari.impl.SelectOptionBuilder(label='TH19',value='19',emoji=town_hall_select_emoji(19)).build()
    assert option['emoji']=={'id':'1571025137896005783'}
    assert not hasattr(emojis,'TH19')


def test_no_snapshot_omits_select_emoji_and_returns_plain_text_fallback(monkeypatch):
    monkeypatch.setattr(town_halls,'_snapshot',None)
    assert town_halls.town_hall_emoji(19)==''
    option=hikari.impl.SelectOptionBuilder(label='TH19',value='19',emoji=town_hall_select_emoji(19)).build()
    assert 'emoji' not in option
    from extensions.commands import cards, linked_accounts
    assert linked_accounts._th_display(19)=='TH19'
    assert 'TH19' in cards._player_line('You','Member','#P2Y',19,None)


def test_all_production_bot_call_sites_use_the_registry():
    violations=[]
    for directory in ['utils','extensions']:
        for path in (ROOT/directory).rglob('*.py'):
            tree=ast.parse(path.read_text())
            th_names = set()
            for node in ast.walk(tree):
                if isinstance(node,ast.Assign) and 'TH' in ast.unparse(node.value):
                    th_names.update(target.id for target in node.targets if isinstance(target,ast.Name))
            for node in ast.walk(tree):
                if isinstance(node,ast.Attribute) and re.fullmatch(r'TH[0-9]+',node.attr):
                    violations.append(str(path.relative_to(ROOT)))
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in {'getattr','hasattr'} and node.args and isinstance(node.args[0],ast.Name) and node.args[0].id=='emojis':
                    argument=ast.unparse(node.args[1]) if len(node.args)>1 else ''
                    if 'TH' in argument or argument in th_names:violations.append(str(path.relative_to(ROOT)))
    assert violations==[]


def test_todo_looks_up_current_snapshot_at_render_time(monkeypatch):
    from extensions.commands import todo
    from types import SimpleNamespace
    doc=install_snapshot(monkeypatch)
    row=SimpleNamespace(town_hall=19,used=0,limit=1,account='Member')
    assert town_halls.town_hall_emoji(19) in todo._row_line(row)
    doc['levels']['19']['emoji']='<:NEW_19:1571025137896005784>'
    assert '<:NEW_19:1571025137896005784>' in todo._row_line(row)


def test_base_menu_options_follow_registry_minimum_keep_upgrade_variants(monkeypatch):
    from utils.emoji import fwa_town_hall_options
    doc=install_snapshot(monkeypatch)
    options=[hikari.impl.SelectOptionBuilder(label=key,value=key) for key in ['th18','th18_new','th12','th11','th9']]
    assert [option.value for option in fwa_town_hall_options(options)]==['th18','th18_new','th12']
    doc['lowest_fwa_town_hall']=18
    assert [option.value for option in fwa_town_hall_options(options)]==['th18','th18_new']


def test_no_matching_legacy_base_data_is_a_disabled_valid_menu(monkeypatch):
    from utils.emoji import fwa_town_hall_options, fwa_town_hall_menu
    doc=install_snapshot(monkeypatch);doc['lowest_fwa_town_hall']=19
    options=fwa_town_hall_options([hikari.impl.SelectOptionBuilder(label='TH18',value='th18')])
    menu=fwa_town_hall_menu(hikari.impl.TextSelectMenuBuilder(custom_id='base:test',options=options))
    assert menu.is_disabled and len(menu.options)==1
    assert menu.options[0].value=='unavailable'


def test_dynamic_requirement_and_dashboard_helpers_read_th19_and_plain_fallback(monkeypatch):
    from extensions.commands.clan.info_hub.helpers import format_th_requirement
    from extensions.commands.clan.dashboard.fwa_data import get_th_emoji
    install_snapshot(monkeypatch)
    assert '<:TH_19A:1571025137896005783>' in format_th_requirement(19,None)
    assert str(get_th_emoji('th19_new'))=='<:TH_19A:1571025137896005783>'
    option=hikari.impl.SelectOptionBuilder(label='TH19',value='19',emoji=get_th_emoji('th19')).build()
    assert option['emoji']=={'id':'1571025137896005783'}
    monkeypatch.setattr(town_halls,'_snapshot',None)
    assert format_th_requirement(19,None)=='TH19+'
    assert get_th_emoji('th19') is None
