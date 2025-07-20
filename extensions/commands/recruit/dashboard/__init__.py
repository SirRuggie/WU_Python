# extensions/commands/recruit/dashboard/__init__.py
"""
Recruit Dashboard Package - Handles all dashboard-related functionality
"""

# Import all dashboard modules to register their actions
from . import dashboard
from . import create_nickname
from . import manage_roles
from . import set_townhall
from . import add_clan_roles
from . import server_walkthrough

# Re-export the main dashboard command for easy access
from .dashboard import RecruitDashboard

__all__ = [
    "RecruitDashboard",
    "dashboard",
    "create_nickname",
    "manage_roles",
    "set_townhall",
    "add_clan_roles",
    "server_walkthrough"
]