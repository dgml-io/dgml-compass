"""The execution rails: a bounded thread pool over draws, with a budget guard that reserves
before a draw starts and settles on its measured cost (DECISIONS 0016), a per-provider rate
limiter, and Ctrl-C handling that stops submission like a budget breach does."""

from __future__ import annotations

import logging
import signal
import threading
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from model_compass.errors import BudgetExceeded, CompassError, ConfigError
from model_compass.experiments.manifest import CellStatus

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

log = logging.getLogger(__name__)


# -- budget, rate limit, cancellation -------------------------------------------------------


class BudgetGuard:
    """Reserve an estimate before a draw starts, settle on its measured cost. Thread-safe."""

    def __init__(self, cap_usd: float) -> None:
        if cap_usd <= 0:
            raise ConfigError("budget cap must be positive", code="budget_invalid")
        self.cap_usd = float(cap_usd)
        self.spent_usd = 0.0
        self.committed_usd = 0.0
        self._lock = threading.Lock()

    def reserve(self, amount: float) -> None:
        with self._lock:
            projected = self.spent_usd + self.committed_usd + max(0.0, amount)
            if projected > self.cap_usd:
                raise BudgetExceeded(
                    f"projected spend ${projected:,.2f} would exceed the cap "
                    f"${self.cap_usd:,.2f} (actual spend so far ${self.spent_usd:,.2f}); "
                    "raise --budget-usd or narrow the experiment",
                    projected_usd=round(projected, 6),
                    actual_usd=round(self.spent_usd, 6),
                    cap_usd=self.cap_usd,
                )
            self.committed_usd += max(0.0, amount)

    def settle(self, reserved: float, actual: float | None) -> None:
        with self._lock:
            self.committed_usd = max(0.0, self.committed_usd - max(0.0, reserved))
            self.spent_usd += max(0.0, actual or 0.0)


@dataclass(frozen=True)
class ProviderLimit:
    requests_per_minute: float = 60.0
    burst: int = 8


DEFAULT_LIMITS: Final[dict[str, ProviderLimit]] = {
    "anthropic": ProviderLimit(240.0, 8),
    "gemini": ProviderLimit(300.0, 10),
    "openai": ProviderLimit(240.0, 8),
}
"""Conservative starting points, not measured limits. Unknown providers are unlimited."""


def provider_of(model_id: str | None) -> str:
    """``anthropic/claude-haiku-4-5`` -> ``anthropic``."""
    if not model_id:
        return "unknown"
    head, separator, _ = model_id.partition("/")
    return head.lower() if separator else model_id.lower()


class RateLimiter:
    """One token bucket per provider; ``acquire`` blocks and returns the seconds waited."""

    def __init__(
        self,
        limits: dict[str, ProviderLimit] | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._limits = DEFAULT_LIMITS if limits is None else limits
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._tokens: dict[str, float] = {}
        self._updated: dict[str, float] = {}

    def _take(self, provider: str) -> float:
        limit = self._limits.get(provider)
        if limit is None:
            return 0.0
        rate = limit.requests_per_minute / 60.0
        now = self._clock()
        with self._lock:
            elapsed = now - self._updated.get(provider, now)
            available = min(
                float(limit.burst), self._tokens.get(provider, limit.burst) + elapsed * rate
            )
            self._updated[provider] = now
            if available >= 1.0:
                self._tokens[provider] = available - 1.0
                return 0.0
            self._tokens[provider] = available
            return (1.0 - available) / rate

    def acquire(self, provider: str) -> float:
        waited = 0.0
        while (delay := self._take(provider)) > 0.0:
            self._sleep(delay)
            waited += delay
        return waited


@contextmanager
def _graceful_sigint(stop: threading.Event) -> Iterator[None]:
    """The first Ctrl-C stops submission; a second one is Python's default. Main thread only."""
    try:
        previous = signal.getsignal(signal.SIGINT)

        def handler(signum: int, frame: Any) -> None:
            stop.set()
            signal.signal(signal.SIGINT, previous)

        signal.signal(signal.SIGINT, handler)
    except ValueError:  # not the main thread
        yield
        return
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)


# -- the pool --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Task:
    cell_id: str
    draw_index: int | None
    """``None`` for a single-draw cell: its events carry no draw index."""
    call: Callable[[], float]
    estimated_usd: float = 0.0
    provider: str | None = None


@dataclass(frozen=True)
class Outcome:
    task: Task
    status: CellStatus
    """``SUCCEEDED``, ``FAILED`` or ``CANCELLED``."""
    cost_usd: float | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class Pool:
    workers: int
    budget: BudgetGuard
    limiter: RateLimiter = field(default_factory=RateLimiter)
    stop: threading.Event = field(default_factory=threading.Event)

    def _execute(self, task: Task) -> Outcome:
        try:
            if task.provider is not None:
                self.limiter.acquire(task.provider)
            return Outcome(task, CellStatus.SUCCEEDED, cost_usd=task.call())
        except Exception as exc:  # a draw must never take the run down
            code = exc.code if isinstance(exc, CompassError) else "task_error"
            if isinstance(exc, TimeoutError):
                code = "timeout"
            spent = exc.context.get("cost_usd") if isinstance(exc, CompassError) else None
            log.warning("draw of %s failed: %s %s", task.cell_id, code, exc)
            return Outcome(
                task,
                CellStatus.FAILED,
                cost_usd=float(spent) if isinstance(spent, int | float) else None,
                error_code=code,
                error_message=str(exc)[:2000],
            )

    def submit(self, tasks: Sequence[Task]) -> Iterator[Outcome]:
        """Yields outcomes as draws finish. On a breach: stop submitting, drain, cancel the
        rest, and only then raise, so the caller can still write a truthful manifest."""
        pending = deque(tasks)
        in_flight: dict[Future[Outcome], Task] = {}
        breach: BudgetExceeded | None = None
        with _graceful_sigint(self.stop), ThreadPoolExecutor(self.workers) as pool:
            while pending or in_flight:
                while (
                    pending
                    and len(in_flight) < self.workers
                    and breach is None
                    and not self.stop.is_set()
                ):
                    try:
                        self.budget.reserve(pending[0].estimated_usd)
                    except BudgetExceeded as exc:
                        breach = exc
                        break
                    task = pending.popleft()
                    in_flight[pool.submit(self._execute, task)] = task
                if not in_flight:
                    break
                done, _ = wait(set(in_flight), return_when=FIRST_COMPLETED)
                for future in done:
                    task = in_flight.pop(future)
                    outcome = future.result()
                    self.budget.settle(task.estimated_usd, outcome.cost_usd)
                    yield outcome
            reason = "budget_exceeded" if breach is not None else "cancelled"
            for task in pending:
                yield Outcome(task, CellStatus.CANCELLED, error_code=reason)
        if breach is not None:
            raise breach

