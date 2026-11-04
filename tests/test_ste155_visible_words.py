"""Owner542/544: visible words omit the internal name; wire/storage syntax stays."""
import ast
from pathlib import Path
import re

import pytest
from utils import cwl_campaign

ROOT = Path(__file__).resolve().parents[1]
FILES = [str(file.relative_to(ROOT)) for folder in ('cwl_web', 'utils', 'extensions')
         for file in sorted((ROOT / folder).rglob('*.py'))]


def _kind_expression(node):
    if isinstance(node, ast.Subscript):
        return isinstance(node.slice, ast.Constant) and node.slice.value == 'kind'
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'get' and node.args
            and isinstance(node.args[0], ast.Constant) and node.args[0].value == 'kind')


def _dict_value_key(node, parents):
    parent = parents.get(node)
    if isinstance(parent, ast.Dict):
        for key, value in zip(parent.keys, parent.values):
            if value is node and isinstance(key, ast.Constant):
                return key.value
    return None


def _internal_draft_purpose(node, parents):
    """Only the internal new_draft purpose-enum precondition, not prose matching."""
    call = parents.get(node)
    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            and call.func.id == 'ValueError' and isinstance(parents.get(call), ast.Raise)):
        return False
    branch = None
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, ast.If) and isinstance(current.test, ast.Compare):
            if isinstance(current.test.left, ast.Name) and current.test.left.id == 'purpose':
                branch = current
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name == 'new_draft' and branch is not None
    return False


def _visible_sink(node, parents):
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, ast.Raise):
            return True
        if isinstance(current, ast.keyword) and current.arg in {'text', 'label', 'title', 'body', 'content', 'description'}:
            return True
        if isinstance(current, ast.Call):
            func = current.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ''
            if re.search(r'reply|respond|embed|button|text_input|modal|label', name, re.I):
                return True
    return False


def visible_violations(source):
    tree = ast.parse(source)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if not re.search(r'\bcampaigns?\b', node.value, re.I):
            continue
        parent = parents.get(node)
        if isinstance(parent, ast.Expr):
            continue  # Docstring, not a response.
        if _internal_draft_purpose(node, parents):
            continue  # Internal purpose enum supplied by code, before data loading.
        if _visible_sink(node, parents):
            violations.append((node.lineno, node.value))
            continue
        current = node
        while current in parents and not isinstance(current, ast.Call):
            current = parents[current]
        if isinstance(current, ast.Call) and isinstance(current.func, ast.Name) and current.func.id == 'print':
            continue  # Worker journal only.
        if isinstance(parent, ast.Dict) and node in parent.keys:
            continue
        if isinstance(parent, ast.Subscript) and parent.slice is node:
            continue
        if isinstance(parent, ast.Call) and parent.args and parent.args[0] is node and isinstance(parent.func, ast.Attribute) and parent.func.attr in {'get', 'pop', 'setdefault'}:
            continue
        if isinstance(parent, ast.Set):
            assignment = parents.get(parent)
            if isinstance(assignment, ast.Assign) and any(isinstance(t, ast.Name) and t.id.startswith('allowed') for t in assignment.targets):
                continue  # An allowed-field-name set, not a list of prose.
        if isinstance(parent, (ast.Tuple, ast.List)) and isinstance(parents.get(parent), ast.Compare):
            if any(isinstance(op, (ast.In, ast.NotIn)) for op in parents[parent].ops):
                continue  # A field-name membership tuple/list.
        if isinstance(parent, ast.Compare):
            if any(isinstance(op, (ast.In, ast.NotIn)) for op in parent.ops):
                continue  # Field-name membership.
            if any(_kind_expression(value) for value in [parent.left, *parent.comparators]):
                continue  # Durable kind comparison.
        key = _dict_value_key(node, parents)
        if key == 'kind':
            continue
        if key in {'$ne', '$eq'} and _dict_value_key(parent, parents) == 'kind':
            continue
        if isinstance(parent, ast.JoinedStr):
            owner = parents.get(parent)
            if isinstance(owner, ast.DictComp) and owner.key is parent or isinstance(owner, ast.Dict) and parent in owner.keys:
                continue  # Computed Mongo field key, not a visible template.
        violations.append((node.lineno, node.value))
    return violations


def test_discord_forms_and_staff_error_literals_use_human_visible_terms():
    violations = [(file, line, text) for file in FILES
                  for line, text in visible_violations((ROOT / file).read_text())]
    assert violations == []


@pytest.mark.parametrize('source', [
    'row = {"campaign": value}',
    'value = row["campaign"]',
    'value = row.get("campaign")',
    'allowed_fields = {"campaign", "scope"}',
    'present = "campaign" in patch',
    'present = key not in ("campaign", "draft_id")',
    'query = {"kind": "campaign"}',
    'same = row.get("kind") == "campaign"',
    'query = {"kind": {"$ne": "campaign"}}',
    'query = {f"campaign.messages.{key}": value for key, value in fields.items()}',
])
def test_machine_syntax_positions_remain_unchanged(source):
    assert visible_violations(source) == []


@pytest.mark.parametrize('source', [
    'reply("Resume the campaign")',
    'reply("Resume campaigns")',
    'Embed(title="Campaigns")',
    'Embed(title="Campaign")',
    'HTTPConflict(text="The campaign changed")',
    'label("Campaign")',
    'raise ValueError("Campaign")',
    'reply({"campaign": value})',
    'Embed(description=f"campaign.messages.{key}")',
    'async def new_draft():\n    if purpose not in (None,):\n        reply("Campaign")',
])
def test_visible_sinks_reject_the_word_even_in_otherwise_exempt_shapes(source):
    assert visible_violations(source)


def test_fresh_discord_message_bodies_titles_labels_and_buttons_have_no_internal_term():
    fresh = cwl_campaign.default_campaign()
    visible = []
    for message in fresh['messages'].values():
        visible.append(message['label'])
        for variant in message['variants'].values():
            visible.extend([variant['title'], variant['body']])
            visible.extend(button.get('label', '') for button in variant['buttons'])
    assert all(not re.search(r'\bcampaigns?\b', text, re.I) for text in visible)
