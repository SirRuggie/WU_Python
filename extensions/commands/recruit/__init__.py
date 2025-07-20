# extensions/commands/recruit/__init__.py
import lightbulb

loader = lightbulb.Loader()
recruit = lightbulb.Group("recruit", "All Recruit-related commands")

# Import all recruit modules
from . import questions
from . import codes
from . import dashboard

__all__ = ["loader", "recruit"]