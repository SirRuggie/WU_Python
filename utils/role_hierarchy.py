"""Request-local role-position index; never a shared authorization cache."""


class RolePositions:
    def __init__(self, roles):
        self.roles = tuple(roles)
        self.positions = {}
        self.tops = {}
        for role in self.roles:
            if role.id not in self.positions or role.position > self.positions[role.id]:
                self.positions[role.id] = role.position

    def __iter__(self):
        return iter(self.roles)

    def top(self, role_ids):
        key = frozenset(role_ids)
        if key not in self.tops:
            self.tops[key] = max(
                (
                    self.positions[role_id]
                    for role_id in key
                    if role_id in self.positions
                ),
                default=0,
            )
        return self.tops[key]
