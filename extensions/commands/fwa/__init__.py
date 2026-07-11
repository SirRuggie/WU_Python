import lightbulb

# WARNING: this `loader` is SHARED by every /fwa command module (each does
# `from extensions.commands.fwa import loader, fwa`). lightbulb re-adds this loader to
# the client once per fwa module that loads, so ANY `@loader.listener(...)` attached to
# it fires once PER fwa module (~9x), not once. If you add a listener here, guard it to
# run a single time (see on_bot_started in lazy_cwl.py) or put it on a module-local
# Loader instead. Commands and components are fine; event listeners are the trap.
loader = lightbulb.Loader()
fwa = lightbulb.Group("fwa", "All FWA-related commands")

# Import all FWA modules
from . import bases
from . import chocolate
from . import lazy_cwl
from . import links
from . import new_th_upgrade
from . import points
from . import upload_images
from . import war_plans
from . import weight

__all__ = ["loader", "fwa"]
