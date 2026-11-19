"""Read-only compatibility adapter for calculator range consumers.

The Town Hall registry owns storage, validation and emoji selection.
"""
from utils.town_halls import weight_ranges


def ranges(config):
    return weight_ranges(config)
