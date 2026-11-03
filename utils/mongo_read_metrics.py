"""Numeric, task-local diagnostics from public PyMongo monitoring events.

No command, document, namespace, address or request identifier is retained.
Checkout duration includes connection establishment when necessary; it is not
proof of network latency or pure wait-queue contention.
"""

from contextvars import ContextVar
from contextlib import contextmanager
from time import perf_counter
from pymongo import monitoring

CURRENT = ContextVar("wu_mongo_read_metrics", default=None)


class ReadMetrics:
    def __init__(self):
        self.started = perf_counter()
        self.checkout_ms = 0.0
        self.command_ms = 0.0
        self.first_response_ms = 0.0
        self.commands = self.responses = self.failures = self.checkouts = 0


@contextmanager
def collect():
    value = ReadMetrics()
    token = CURRENT.set(value)
    try:
        yield value
    finally:
        CURRENT.reset(token)


class NumericReadListener(
    monitoring.CommandListener, monitoring.ConnectionPoolListener
):
    def started(self, event):
        value = CURRENT.get()
        if value is not None:
            value.commands += 1

    def succeeded(self, event):
        value = CURRENT.get()
        if value is not None:
            value.command_ms += event.duration_micros / 1000
            if not value.responses:
                value.first_response_ms = (perf_counter() - value.started) * 1000
            value.responses += 1

    def failed(self, event):
        value = CURRENT.get()
        if value is not None:
            value.failures += 1
            value.command_ms += event.duration_micros / 1000

    def connection_checked_out(self, event):
        value = CURRENT.get()
        if value is not None:
            value.checkouts += 1
            value.checkout_ms += (event.duration or 0) * 1000

    def connection_check_out_failed(self, event):
        value = CURRENT.get()
        if value is not None:
            value.checkout_ms += (event.duration or 0) * 1000

    def pool_created(self, event):
        pass

    def pool_ready(self, event):
        pass

    def pool_cleared(self, event):
        pass

    def pool_closed(self, event):
        pass

    def connection_created(self, event):
        pass

    def connection_ready(self, event):
        pass

    def connection_closed(self, event):
        pass

    def connection_check_out_started(self, event):
        pass

    def connection_checked_in(self, event):
        pass
