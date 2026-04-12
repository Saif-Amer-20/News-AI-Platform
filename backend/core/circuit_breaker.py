"""Circuit breaker and retry utilities for external service calls.

Provides a lightweight circuit breaker that opens when a service has too
many consecutive failures, preventing cascading failures.  After a
cooldown period, half-open probes allow recovery.
"""
from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised when a call is attempted on an open circuit."""

    def __init__(self, service: str, cooldown_remaining: float):
        self.service = service
        self.cooldown_remaining = cooldown_remaining
        super().__init__(
            f"Circuit breaker OPEN for '{service}'. "
            f"Retry in {cooldown_remaining:.0f}s."
        )


class CircuitBreaker:
    """Per-service circuit breaker.

    Parameters
    ----------
    service : str
        Name of the external service (e.g. "opensearch", "neo4j").
    failure_threshold : int
        Number of consecutive failures before opening the circuit.
    cooldown_seconds : float
        Seconds to wait before allowing a half-open probe.
    success_threshold : int
        Consecutive successes in half-open state to close the circuit.
    """

    def __init__(
        self,
        service: str,
        failure_threshold: int = 5,
        cooldown_seconds: float = 60.0,
        success_threshold: int = 2,
    ):
        self.service = service
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.success_threshold = success_threshold

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                elapsed = time.monotonic() - self._last_failure_time
                if elapsed >= self.cooldown_seconds:
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0
                    logger.info(
                        "Circuit breaker %s: OPEN → HALF_OPEN after %.0fs cooldown",
                        self.service, elapsed,
                    )
            return self._state

    def record_success(self):
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    logger.info(
                        "Circuit breaker %s: HALF_OPEN → CLOSED", self.service
                    )
            else:
                self._failure_count = 0

    def record_failure(self):
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning(
                    "Circuit breaker %s: HALF_OPEN → OPEN (probe failed)",
                    self.service,
                )
            elif self._failure_count >= self.failure_threshold:
                if self._state != CircuitState.OPEN:
                    self._state = CircuitState.OPEN
                    logger.warning(
                        "Circuit breaker %s: CLOSED → OPEN after %d failures",
                        self.service, self._failure_count,
                    )

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute func through the circuit breaker."""
        state = self.state
        if state == CircuitState.OPEN:
            remaining = self.cooldown_seconds - (
                time.monotonic() - self._last_failure_time
            )
            raise CircuitOpenError(self.service, max(0, remaining))

        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except CircuitOpenError:
            raise
        except Exception:
            self.record_failure()
            raise

    def reset(self):
        """Manually reset the circuit breaker to closed state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            logger.info("Circuit breaker %s: manually reset to CLOSED", self.service)


# ── Global registry ───────────────────────────────────────────────────────

_registry: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_circuit_breaker(
    service: str,
    failure_threshold: int = 5,
    cooldown_seconds: float = 60.0,
) -> CircuitBreaker:
    """Get or create a circuit breaker for a service."""
    with _registry_lock:
        if service not in _registry:
            _registry[service] = CircuitBreaker(
                service,
                failure_threshold=failure_threshold,
                cooldown_seconds=cooldown_seconds,
            )
        return _registry[service]


def circuit_breaker(
    service: str,
    failure_threshold: int = 5,
    cooldown_seconds: float = 60.0,
):
    """Decorator that wraps a function with a circuit breaker.

    Usage::

        @circuit_breaker("opensearch")
        def search_articles(query):
            ...
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cb = get_circuit_breaker(service, failure_threshold, cooldown_seconds)
            return cb.call(func, *args, **kwargs)

        wrapper._circuit_breaker_service = service
        return wrapper

    return decorator
