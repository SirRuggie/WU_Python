# extensions/commands/setup/__init__.py
import lightbulb

loader = lightbulb.Loader()
setup = lightbulb.Group("setup", "Server setup and configuration commands")

# Import all setup modules
from . import recruit_aboutus
from . import recruit_strikesystem
from . import recruit_familyparticulars

__all__ = ["loader", "setup"]