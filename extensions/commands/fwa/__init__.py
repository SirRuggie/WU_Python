import lightbulb

loader = lightbulb.Loader()
fwa = lightbulb.Group("fwa", "All FWA-related commands")

# Import all FWA modules
from . import bases
from . import chocolate
from . import lazy_cwl
from . import links
from . import upload_images
from . import war_plans
from . import weight

__all__ = ["loader", "fwa"]
