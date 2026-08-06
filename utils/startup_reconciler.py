"""Self-healing, idempotent startup reconciliation for background subsystems."""

import asyncio
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


DEFAULT_RETRY_DELAYS_SECONDS = (5, 15, 30, 60, 300)
ERROR_DETAIL_LIMIT = 180


@dataclass
class StartupHealth:
    state: str = "stopped"
    attempts: int = 0
    last_error_type: str | None = None
    last_error: str | None = None
    last_failure_at: datetime | None = None
    next_retry_at: datetime | None = None
    recovered_at: datetime | None = None


def _error_detail(exc: Exception) -> str:
    detail = " ".join(str(exc).split()) or "no error detail"
    detail = re.sub(
        r"(?i)\b(mongodb(?:\+srv)?|https?)://[^@\s]+@",
        r"\1://***@",
        detail,
    )
    detail = re.sub(
        r"(?i)\b(access_token|token|api_key|secret|password)=([^&\s]+)",
        r"\1=***",
        detail,
    )
    return detail[:ERROR_DETAIL_LIMIT]


class StartupReconciler:
    """Retry a subsystem's startup operation without blocking bot startup.

    The supplied operation must be idempotent. A successful operation ends the
    retry task and leaves health in ``healthy``. Failures retry forever at a
    capped cadence because a continuously running bot should recover when its
    dependency does.
    """

    def __init__(
        self,
        name: str,
        operation: Callable[[], Awaitable[None]],
        *,
        retry_delays: Sequence[float] = DEFAULT_RETRY_DELAYS_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not retry_delays or any(delay < 0 for delay in retry_delays):
            raise ValueError("retry_delays must contain non-negative values")
        self.name = name
        self.operation = operation
        self.retry_delays = tuple(retry_delays)
        self.sleep = sleep
        self.health = StartupHealth()
        self.task: asyncio.Task | None = None

    def start(self) -> asyncio.Task | None:
        """Start once; duplicate startup events cannot create duplicate work."""
        if self.health.state == "healthy":
            return self.task
        if self.task and not self.task.done():
            return self.task
        self.health = StartupHealth(state="starting")
        self.task = asyncio.create_task(
            self._run(),
            name=f"startup-reconcile:{self.name}",
        )
        return self.task

    async def _run(self) -> None:
        while True:
            self.health.attempts += 1
            try:
                await self.operation()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                now = datetime.now(timezone.utc)
                delay_index = min(
                    self.health.attempts - 1,
                    len(self.retry_delays) - 1,
                )
                delay = self.retry_delays[delay_index]
                self.health.state = "retrying"
                self.health.last_error_type = type(exc).__name__
                self.health.last_error = _error_detail(exc)
                self.health.last_failure_at = now
                self.health.next_retry_at = now + timedelta(seconds=delay)

                # Log the initial backoff ramp and then once per hour at the
                # five-minute cap. Health remains queryable between log lines.
                should_log = (
                    self.health.attempts <= len(self.retry_delays)
                    or (self.health.attempts - len(self.retry_delays)) % 12 == 0
                )
                if should_log:
                    print(
                        f"[Startup] startup_reconcile_retry subsystem={self.name} "
                        f"attempt={self.health.attempts} delay_seconds={delay:g} "
                        f"error={self.health.last_error_type} "
                        f"detail={self.health.last_error}"
                    )
                await self.sleep(delay)
                continue

            recovered = self.health.attempts > 1
            self.health.state = "healthy"
            self.health.last_error_type = None
            self.health.last_error = None
            self.health.next_retry_at = None
            self.health.recovered_at = datetime.now(timezone.utc)
            marker = "startup_reconcile_recovered" if recovered else "startup_reconcile_healthy"
            print(
                f"[Startup] {marker} subsystem={self.name} "
                f"attempts={self.health.attempts}"
            )
            return

    async def stop(self) -> None:
        task = self.task
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.task = None
        self.health.state = "stopped"
        self.health.next_retry_at = None

    def status_text(self) -> str:
        if self.health.state == "healthy":
            return "✅ Healthy"
        if self.health.state == "retrying":
            error = self.health.last_error_type or "dependency error"
            return f"⚠️ Recovering after {error} (attempt {self.health.attempts})"
        if self.health.state == "starting":
            return "⏳ Starting"
        return "⏹️ Stopped"
