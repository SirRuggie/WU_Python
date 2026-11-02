"""Per-operation budgets for a collection on the shared HTTP Mongo pool.

Never hold CSOT across a caller's workflow: it may await Discord or spawn tasks.
Cursor consumption gets a fresh budget for each database operation as well.
"""

import inspect
from functools import wraps

from pymongo import timeout


class BudgetedCollection:
    def __init__(self, collection, seconds):
        self.collection = collection
        self.seconds = seconds

    def __getattr__(self, name):
        method = getattr(self.collection, name)
        if inspect.iscoroutinefunction(method):

            @wraps(method)
            async def operation(*args, **kwargs):
                with timeout(self.seconds):
                    result = await method(*args, **kwargs)
                return self._wrap(result)

            return operation
        if name in {"find", "with_options"}:

            @wraps(method)
            def cursor_or_collection(*args, **kwargs):
                return self._wrap(method(*args, **kwargs))

            return cursor_or_collection
        return method

    def _wrap(self, result):
        if hasattr(result, "to_list") and hasattr(result, "__aiter__"):
            return BudgetedCursor(result, self.seconds)
        if hasattr(result, "find_one") and hasattr(result, "with_options"):
            return BudgetedCollection(result, self.seconds)
        return result


class BudgetedCursor:
    def __init__(self, cursor, seconds):
        self.cursor = cursor
        self.seconds = seconds

    def __aiter__(self):
        return self

    async def __aenter__(self):
        with timeout(self.seconds):
            await self.cursor.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        with timeout(self.seconds):
            return await self.cursor.__aexit__(exc_type, exc, traceback)

    async def __anext__(self):
        with timeout(self.seconds):
            return await self.cursor.__anext__()

    def __getattr__(self, name):
        method = getattr(self.cursor, name)
        if inspect.iscoroutinefunction(method):

            @wraps(method)
            async def operation(*args, **kwargs):
                with timeout(self.seconds):
                    return await method(*args, **kwargs)

            return operation
        if callable(method):

            @wraps(method)
            def configure(*args, **kwargs):
                result = method(*args, **kwargs)
                if result is self.cursor:
                    return self
                if hasattr(result, "to_list") and hasattr(result, "__aiter__"):
                    return BudgetedCursor(result, self.seconds)
                return result

            return configure
        return method
