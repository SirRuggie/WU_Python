"""Privacy-safe, best-effort request timings for the Members overview only."""

from contextlib import contextmanager, nullcontext
import logging
from time import perf_counter

LOG = logging.getLogger("cwl_web.member_timezones")
STAGES = ("directory_ms", "hierarchy_ms", "profiles_ms", "rows_ms", "json_ms")


def clock():
    try:
        return perf_counter()
    except Exception:
        return None


def elapsed(start):
    end = clock()
    try:
        return (
            max(0.0, (end - start) * 1000)
            if start is not None and end is not None
            else 0.0
        )
    except Exception:
        return 0.0


class OverviewTiming:
    def __init__(self):
        self.started = clock()
        self.values = {key: 0.0 for key in STAGES}
        self.members = self.roles = self.pages = self.requests = 0

    @contextmanager
    def measure(self, name):
        start = clock()
        try:
            yield
        finally:
            try:
                self.values[name] += elapsed(start)
            except Exception:
                pass

    def page(self):
        try:
            self.pages += 1
        except Exception:
            pass

    def discord(self):
        try:
            self.requests += 1
        except Exception:
            pass

    def counts(self, members, roles):
        try:
            self.members, self.roles = int(members), int(roles)
        except Exception:
            pass

    def emit(self, response):
        try:
            size = len(getattr(response, "body", None) or b"")
            LOG.info(
                "Members overview timing directory_ms=%.1f hierarchy_ms=%.1f profiles_ms=%.1f rows_ms=%.1f json_ms=%.1f total_ms=%.1f members=%d roles=%d discord_pages=%d discord_requests=%d bytes=%d",
                *(self.values[key] for key in STAGES),
                elapsed(self.started),
                self.members,
                self.roles,
                self.pages,
                self.requests,
                size
            )
        except Exception:
            # Observability must never change an authorization or response outcome.
            pass


class NoTiming:
    def measure(self, name):
        return nullcontext()

    def page(self):
        pass

    def discord(self):
        pass

    def counts(self, members, roles):
        pass

    def emit(self, response):
        pass


def start_timing():
    try:
        return OverviewTiming()
    except Exception:
        return NoTiming()


def measure(timing, name):
    return timing.measure(name) if timing is not None else nullcontext()


KEY = "_wu_members_overview_timing"
MISSING = object()


def bind(request, timing):
    try:
        old = request.get(KEY, MISSING)
        request[KEY] = timing
        return "mapping", old
    except Exception:
        try:
            old = getattr(request, KEY, MISSING)
            setattr(request, KEY, timing)
            return "attribute", old
        except Exception:
            return None


def unbind(request, binding):
    try:
        mode, old = binding
        if mode == "mapping":
            if old is MISSING:
                del request[KEY]
            else:
                request[KEY] = old
        elif old is MISSING:
            delattr(request, KEY)
        else:
            setattr(request, KEY, old)
    except Exception:
        pass


def note_discord(request):
    try:
        try:
            timing = request.get(KEY)
        except AttributeError:
            timing = getattr(request, KEY, None)
        if timing is not None:
            timing.discord()
    except Exception:
        pass
