"""Owner-approved 712 wording is present at each designated producer."""
import ast
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]

def constants(path):
    tree = ast.parse((ROOT / path).read_text())
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]

@pytest.mark.parametrize(('path','text','count'), [
 ('extensions/commands/cwl_member.py','CWL is temporarily unavailable. Your saved signups did not change. Try /cwl signup again in a few minutes.',3),
 ('extensions/commands/accounts.py','Try `/user-accounts` again in a few minutes.',1),
 ('extensions/commands/accounts.py','Their linked tags are shown above. Try again in a few minutes.',1),
 ('extensions/commands/content.py','Select a supported post.',1),
 ('extensions/commands/warrior.py',"Select an unmanaged role below the Warriors United app's highest role.",1),
 ('extensions/commands/tickets/rite.py','Select this path if you are ready to prove your worth and rise among your fellow warriors.',1),
 ('utils/ticket_staff_content.py','Select Main or FWA.',1),
 ('extensions/commands/tickets/close.py','✅ Ticket denied with the FWA message.',1),
 ('extensions/commands/tickets/close.py','✅ Ticket denied with the Main message.',1),
 ('extensions/commands/manage.py','FWA Clan Rep role',3),
])
def test_exact_approved_text_at_named_producer(path, text, count):
    assert sum(value.count(text) for value in constants(path)) == count

def test_rite_preserves_oath_and_custom_id():
    values = constants('extensions/commands/tickets/rite.py')
    assert any('only the path you take and the oath you are willing to take.”**' in v for v in values)
    assert any('ticket_v2_rite_choose:' in v for v in values)

def test_conditional_title_keeps_other_verb_label():
    tree=ast.parse((ROOT/'extensions/commands/tickets/console.py').read_text())
    conditions=[n for n in ast.walk(tree) if isinstance(n,ast.IfExp) and isinstance(n.body,ast.Constant) and n.body.value=='Not approved']
    assert len(conditions)==1
    assert ast.unparse(conditions[0].test)=="verb == 'approved'"
    assert isinstance(conditions[0].orelse,ast.Constant) and conditions[0].orelse.value=='Not completed'

def test_console_forbidden_and_multi_account_interpolation_exact():
    checks=[('extensions/commands/tickets/console.py',"f'Saved console channel {existing_channel_id} cannot be opened. Restore channel access, then try again.'"),('extensions/commands/accounts.py',"f'⚠️ **Could not load {data.error_count} accounts.** Their linked tags are shown above. Try again in a few minutes.'")]
    for path, wanted in checks:
        tree=ast.parse((ROOT/path).read_text())
        assert wanted in [ast.unparse(n) for n in ast.walk(tree) if isinstance(n,ast.JoinedStr)]
