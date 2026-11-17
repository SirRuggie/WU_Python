"""Small source-provenance audit for the dashboard's synchronous publishers.

This resolves imports, constructors, local/bound aliases, factory returns, class
attributes and arguments passed between tracked functions. It is deliberately
not a Python interpreter: dynamic getattr/container dispatch and external caller
injection remain review obligations. Namespace identity, rather than a method
name such as configure(), distinguishes unrelated async Mongo services.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass

IMAGE_STORE = 'utils.cwl_roster_image_store.RosterImageStore'
SQLITE_STORE = 'cwl_web.store.Store'
OFFLOAD = {SQLITE_STORE + '.run_writer', SQLITE_STORE + '.run_tx', SQLITE_STORE + '.run_role_tx'}


@dataclass
class Function:
    name: str
    module: str
    node: ast.FunctionDef | ast.AsyncFunctionDef
    owner: str | None
    enclosing: str | None


class PublisherAudit:
    def __init__(self, sources: dict[str, str]):
        self.trees = {module: ast.parse(source) for module, source in sources.items()}
        self.functions: dict[str, Function] = {}
        self.classes = set()
        self.parents = {}
        self.bindings = {}
        self.parameters = {}
        self.attributes = {}
        self.returns = {}
        self.tuple_returns = {}
        self.globals = {}
        self.call_targets = {}
        self.call_scopes = {}
        self._index()
        self.nodes = {name: list(self._own_nodes(function))
                      for name, function in self.functions.items()}
        self.children = {}
        for name, function in self.functions.items():
            if function.enclosing:
                self.children.setdefault(function.enclosing, {})[function.node.name] = {name}
        for module, tree in self.trees.items():
            env = self._imports(tree.body, module)
            for name, function in self.functions.items():
                if function.module == module and not function.enclosing and not function.owner:
                    env[function.node.name] = {name}
            for name in self.classes:
                if name.rpartition('.')[0] == module:
                    env[name.rpartition('.')[2]] = {name}
            self.globals[module] = env
        self.publishers = self._publishers()
        self._resolve()

    def _index(self):
        for module, tree in self.trees.items():
            self.parents.update({child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)})
            def index(nodes, prefix, owner=None, enclosing=None):
                for node in nodes:
                    if isinstance(node, ast.ClassDef):
                        name = prefix + '.' + node.name
                        self.classes.add(name)
                        index(node.body, name, name, enclosing)
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        name = prefix + '.' + node.name
                        self.functions[name] = Function(name, module, node, owner, enclosing)
                        self.bindings[name] = {}
                        self.parameters[name] = {}
                        self.returns[name] = set()
                        index(node.body, name, owner, name)
                    else:
                        # Find definitions under if/try/with without entering a
                        # function or class twice.
                        for child in ast.iter_child_nodes(node):
                            if isinstance(child, ast.stmt):
                                index([child], prefix, owner, enclosing)
            index(tree.body, module)

    def _own_nodes(self, function):
        if hasattr(self, "nodes"):
            return iter(self.nodes[function.name])
        def walk(node):
            yield node
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node is not function.node:
                return
            for child in ast.iter_child_nodes(node):
                yield from walk(child)
        return walk(function.node)

    def _imports(self, nodes, module):
        result = {}
        for node in nodes:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    result[alias.asname or alias.name.split('.')[0]] = {alias.name if alias.asname else alias.name.split('.')[0]}
            elif isinstance(node, ast.ImportFrom):
                target = node.module or ''
                if node.level:
                    parts = module.split('.')[:-node.level]
                    target = '.'.join(parts + ([target] if target else []))
                for alias in node.names:
                    result[alias.asname or alias.name] = {target + '.' + alias.name}
        return result

    @staticmethod
    def _merge(mapping, key, values):
        before = len(mapping.get(key, set()))
        mapping.setdefault(key, set()).update(values)
        return len(mapping[key]) != before

    def _value(self, node, env, function):
        if node is None:
            return set()
        if isinstance(node, ast.Name):
            return env.get(node.id, set())
        if isinstance(node, ast.Attribute):
            result = set()
            for value in self._value(node.value, env, function):
                if value.startswith('@'):
                    owner = value[1:]
                    result.update(self.attributes.get((owner, node.attr), set()))
                    method = owner + '.' + node.attr
                    if method in self.functions or method in self.publishers or method in OFFLOAD:
                        result.add(method)
                else:
                    result.add(value + '.' + node.attr)
            return result
        if isinstance(node, ast.Subscript):
            # This is the existing dashboard app's public storage contract.
            if isinstance(node.slice, ast.Constant) and node.slice.value == 'store':
                return {'@' + SQLITE_STORE}
        if isinstance(node, ast.Call):
            result = set()
            for target in self._value(node.func, env, function):
                if target in self.classes:
                    result.add('@' + target)
                result.update(self.returns.get(target, set()))
            return result
        if isinstance(node, (ast.IfExp, ast.BoolOp)):
            values = [node.body, node.orelse] if isinstance(node, ast.IfExp) else node.values
            return set().union(*(self._value(value, env, function) for value in values))
        if isinstance(node, ast.Await):
            return self._value(node.value, env, function)
        return set()

    def _publishers(self):
        result = set()
        for name, function in self.functions.items():
            if isinstance(function.node, ast.AsyncFunctionDef):
                continue
            if function.owner not in {IMAGE_STORE, SQLITE_STORE} and name not in {
                'utils.cwl_member_service.withdraw', 'utils.owner_prank_store.apply',
            }:
                continue
            if function.node.name.startswith('_') or function.enclosing:
                continue
            if any(isinstance(node, ast.With) and any(
                isinstance(item.context_expr, ast.Call)
                and isinstance(item.context_expr.func, ast.Attribute)
                and item.context_expr.func.attr in {'tx', 'role_tx'}
                for item in node.items
            ) for node in self._own_nodes(function)):
                result.add(name)
        # Recovery publishes through the durable owner without a tx() wrapper.
        result.update({SQLITE_STORE + '.recover_durability', SQLITE_STORE + '.flush_role_progress'})
        return result

    def _shape(self, node, env, function):
        if isinstance(node, (ast.Tuple, ast.List)):
            return [self._value(item, env, function) for item in node.elts]
        if isinstance(node, ast.Call):
            result = []
            for target in self._value(node.func, env, function):
                shape = self.tuple_returns.get(target, [])
                while len(result) < len(shape):
                    result.append(set())
                for destination, values in zip(result, shape):
                    destination.update(values)
            return result
        return []

    def _assign(self, target, value, env, function):
        if isinstance(target, (ast.Tuple, ast.List)):
            for child, values in zip(target.elts, self._shape(value, env, function)):
                self._bind(child, values, env, function)
        else:
            self._bind(target, self._value(value, env, function), env, function)

    def _bind(self, target, values, env, function):
        if isinstance(target, ast.Name):
            self._merge(env, target.id, values)
        elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == 'self' and function is not None and function.owner:
            self._merge(self.attributes, (function.owner, target.attr), values)

    def _pass_arguments(self, target, call, env, caller):
        callee = self.functions.get(target)
        if callee is None:
            return
        args = callee.node.args.posonlyargs + callee.node.args.args
        if callee.owner and args and args[0].arg in {'self', 'cls'}:
            args = args[1:]
        for parameter, argument in zip(args, call.args):
            self._merge(self.parameters[target], parameter.arg, self._value(argument, env, caller))
        for keyword in call.keywords:
            if keyword.arg:
                self._merge(self.parameters[target], keyword.arg, self._value(keyword.value, env, caller))

    def _resolve(self):
        # Finite union analysis. No type is removed; a fixed point terminates
        # even when tracked factories or functions recurse.
        def size():
            maps = [*self.bindings.values(), *self.parameters.values(), self.attributes,
                    self.returns, *self.globals.values()]
            return sum(len(values) for mapping in maps for values in mapping.values()) + sum(
                len(values) for shape in self.tuple_returns.values() for values in shape)
        for _ in range(40):
            before = size()
            for module, tree in self.trees.items():
                env = self.globals[module]
                for node in tree.body:
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            self._assign(target, node.value, env, None)
            for name, function in self.functions.items():
                env = self.bindings[name]
                for key, values in self.globals[function.module].items():
                    self._merge(env, key, values)
                if function.enclosing:
                    for key, values in self.bindings[function.enclosing].items():
                        self._merge(env, key, values)
                for key, values in self.children.get(name, {}).items():
                    self._merge(env, key, values)
                for key, values in self._imports(self._own_nodes(function), function.module).items():
                    self._merge(env, key, values)
                for key, values in self.parameters[name].items():
                    self._merge(env, key, values)
                if function.owner:
                    self._merge(env, 'self', {'@' + function.owner})
                for node in self._own_nodes(function):
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            self._assign(target, node.value, env, function)
                    elif isinstance(node, ast.AnnAssign):
                        self._assign(node.target, node.value, env, function)
                    elif isinstance(node, ast.Return):
                        self.returns[name].update(self._value(node.value, env, function))
                        shape = self._shape(node.value, env, function)
                        saved = self.tuple_returns.setdefault(name, [])
                        while len(saved) < len(shape):
                            saved.append(set())
                        for destination, values in zip(saved, shape):
                            destination.update(values)
                    elif isinstance(node, ast.Call):
                        targets = self._value(node.func, env, function)
                        self.call_targets[node] = targets
                        self.call_scopes[node] = name
                        for target in targets:
                            self._pass_arguments(target + '.__init__' if target in self.classes else target, node, env, function)
            if size() == before:
                break
        else:
            raise AssertionError('Publisher provenance did not converge')

    def inventory(self):
        offloaded_functions = set()
        for call, targets in self.call_targets.items():
            if targets & OFFLOAD and call.args:
                scope = self.call_scopes[call]
                offloaded_functions.update(self._value(
                    call.args[0], self.bindings[scope], self.functions[scope]))
        rows = []
        for call, targets in self.call_targets.items():
            publishing = sorted(targets & self.publishers)
            if publishing:
                scope = self.call_scopes[call]
                rows.append({'module': self.functions[scope].module, 'line': call.lineno,
                             'scope': scope, 'publishers': publishing,
                             'receiver': ast.unparse(call.func),
                             'offloaded': self._inside_offload(call) or scope in offloaded_functions})
        return sorted(rows, key=lambda row: (row['module'], row['line']))

    def _inside_offload(self, node):
        parent = self.parents.get(node)
        while parent is not None:
            if isinstance(parent, ast.Lambda):
                wrapper = self.parents.get(parent)
                return isinstance(wrapper, ast.Call) and bool(self.call_targets.get(wrapper, set()) & OFFLOAD)
            if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return False
            parent = self.parents.get(parent)
        return False

    def violations(self):
        # Summarize synchronous helper calls too: a nested def is not proof of
        # offloading if its caller immediately invokes it on the async thread.
        sync_publishers = set(self.publishers)
        for _ in range(len(self.functions) + 1):
            before = len(sync_publishers)
            for call, targets in self.call_targets.items():
                scope = self.call_scopes[call]
                if targets & sync_publishers and not self._inside_offload(call):
                    if not isinstance(self.functions[scope].node, ast.AsyncFunctionDef):
                        sync_publishers.add(scope)
            if len(sync_publishers) == before:
                break
        result = []
        for call, targets in self.call_targets.items():
            scope = self.call_scopes[call]
            if targets & sync_publishers and isinstance(self.functions[scope].node, ast.AsyncFunctionDef) and not self._inside_offload(call):
                result.append({'module': self.functions[scope].module, 'line': call.lineno,
                               'scope': scope, 'publishers': sorted(targets & sync_publishers),
                               'expression': ast.unparse(call)})
        for call, targets in self.call_targets.items():
            async_targets = {target for target in targets
                             if target in self.functions
                             and isinstance(self.functions[target].node, ast.AsyncFunctionDef)}
            if not async_targets:
                continue
            parent = self.parents.get(call)
            while parent is not None and not isinstance(parent, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef)):
                parent = self.parents.get(parent)
            if isinstance(parent, ast.Lambda):
                wrapper = self.parents.get(parent)
                if (isinstance(wrapper, ast.Call) and isinstance(wrapper.func, ast.Attribute)
                        and wrapper.func.attr in {'run_writer', 'run_tx', 'run_role_tx'}):
                    scope = self.call_scopes[call]
                    result.append({'module': self.functions[scope].module, 'line': call.lineno,
                                   'scope': scope, 'async_in_sync_writer': sorted(async_targets),
                                   'expression': ast.unparse(call)})
        return sorted(result, key=lambda row: (row['module'], row['line']))

    def unresolved_method_candidates(self):
        """Review inventory only; name collisions are never silently allowlisted."""
        methods = {name.rpartition('.')[2] for name in self.publishers}
        rows = []
        for call, targets in self.call_targets.items():
            scope = self.call_scopes[call]
            if (isinstance(call.func, ast.Attribute) and call.func.attr in methods
                    and isinstance(self.functions[scope].node, ast.AsyncFunctionDef)
                    and not targets):
                rows.append({'module': self.functions[scope].module, 'line': call.lineno,
                             'scope': scope, 'expression': ast.unparse(call)})
        return sorted(rows, key=lambda row: (row['module'], row['line']))
