"""CWL web application and shared management adapters.

Keep application setup lazy so the bot worker can import shared adapters without
loading web-only endpoints or starting a second service.
"""


def create_app(*args, **kwargs):
    from .app import create_app as factory
    return factory(*args, **kwargs)


__all__ = ['create_app']
