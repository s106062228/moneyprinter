"""
Retry and error recovery utilities for MoneyPrinter.

Provides decorators and helpers for automatic retry with exponential backoff,
designed for resilient video generation pipelines and API calls.
"""

import time
import functools
import logging
from typing import Callable, Tuple, Type, Optional

from mp_logger import get_logger

logger = get_logger("retry")

# Default configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 60.0  # seconds
DEFAULT_BACKOFF_FACTOR = 2.0


def retry(
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable] = None,
):
    """
    Decorator that retries a function with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay between retries in seconds.
        max_delay: Maximum delay between retries in seconds.
        backoff_factor: Multiplier applied to delay after each retry.
        retryable_exceptions: Tuple of exception types that trigger a retry.
        on_retry: Optional callback(attempt, exception, delay) called before each retry.

    Returns:
        Decorated function with retry behavior.

    Example:
        @retry(max_retries=3, retryable_exceptions=(ConnectionError, TimeoutError))
        def upload_video(path):
            ...
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            delay = base_delay

            for attempt in range(1, max_retries + 2):  # +1 for initial + retries
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as exc:
                    last_exception = exc

                    if attempt > max_retries:
                        logger.error(
                            "Function '%s' failed after %d attempts. Last error: %s",
                            func.__name__,
                            max_retries + 1,
                            type(exc).__name__,
                        )
                        raise

                    logger.warning(
                        "Function '%s' attempt %d/%d failed: %s. Retrying in %.1fs...",
                        func.__name__,
                        attempt,
                        max_retries + 1,
                        type(exc).__name__,
                        delay,
                    )

                    if on_retry:
                        on_retry(attempt, exc, delay)

                    time.sleep(delay)
                    delay = min(delay * backoff_factor, max_delay)

            # Should not reach here, but just in case
            raise last_exception  # type: ignore[misc]

        return wrapper

    return decorator


def retry_call(
    func: Callable,
    args: tuple = (),
    kwargs: Optional[dict] = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    """
    Calls a function with retry logic (non-decorator version).

    Args:
        func: The function to call.
        args: Positional arguments for the function.
        kwargs: Keyword arguments for the function.
        max_retries: Maximum retry attempts.
        base_delay: Initial delay between retries.
        max_delay: Maximum delay cap.
        backoff_factor: Delay multiplier per retry.
        retryable_exceptions: Exception types that trigger retry.

    Returns:
        The return value of the function.

    Raises:
        The last exception if all retries are exhausted.
    """
    if kwargs is None:
        kwargs = {}

    last_exception = None
    delay = base_delay

    for attempt in range(1, max_retries + 2):
        try:
            return func(*args, **kwargs)
        except retryable_exceptions as exc:
            last_exception = exc

            if attempt > max_retries:
                logger.error(
                    "Function '%s' failed after %d attempts. Last error: %s",
                    func.__name__,
                    max_retries + 1,
                    type(exc).__name__,
                )
                raise

            logger.warning(
                "Function '%s' attempt %d/%d failed: %s. Retrying in %.1fs...",
                func.__name__,
                attempt,
                max_retries + 1,
                type(exc).__name__,
                delay,
            )

            time.sleep(delay)
            delay = min(delay * backoff_factor, max_delay)

    raise last_exception  # type: ignore[misc]


class PipelineStage:
    """
    Represents a stage in a content generation pipeline with built-in
    retry and error recovery.

    Example:
        stages = [
            PipelineStage("Generate Topic", youtube.generate_topic),
            PipelineStage("Generate Script", youtube.generate_script),
            PipelineStage("Generate TTS", lambda: tts.synthesize(script)),
        ]
        results = run_pipeline(stages)
    """

    def __init__(
        self,
        name: str,
        func: Callable,
        max_retries: int = DEFAULT_MAX_RETRIES,
        required: bool = True,
    ):
        self.name = name
        self.func = func
        self.max_retries = max_retries
        self.required = required
        self.result = None
        self.error = None
        self.attempts = 0

    def execute(self) -> bool:
        """
        Executes this pipeline stage with retry logic.

        Returns:
            True if the stage succeeded, False otherwise.
        """
        try:
            self.result = retry_call(
                self.func,
                max_retries=self.max_retries,
                retryable_exceptions=(Exception,),
            )
            self.error = None
            return True
        except Exception as exc:
            self.error = exc
            logger.error("Pipeline stage '%s' failed: %s", self.name, type(exc).__name__)
            return False


def run_pipeline(stages: list) -> dict:
    """
    Executes a series of pipeline stages in order with error recovery.

    Args:
        stages: List of PipelineStage objects.

    Returns:
        Dict with keys:
            - 'success': bool — whether all required stages passed
            - 'results': dict mapping stage name to its result
            - 'errors': dict mapping failed stage name to its error
            - 'completed': int — number of stages that completed
            - 'total': int — total number of stages
    """
    results = {}
    errors = {}
    completed = 0

    for stage in stages:
        logger.info("Pipeline: Starting stage '%s'...", stage.name)

        success = stage.execute()

        if success:
            results[stage.name] = stage.result
            completed += 1
            logger.info("Pipeline: Stage '%s' completed successfully.", stage.name)
        else:
            errors[stage.name] = type(stage.error).__name__
            if stage.required:
                logger.error(
                    "Pipeline: Required stage '%s' failed. Aborting pipeline.",
                    stage.name,
                )
                break
            else:
                logger.warning(
                    "Pipeline: Optional stage '%s' failed. Continuing...",
                    stage.name,
                )

    all_required_passed = all(
        stage.error is None for stage in stages if stage.required
    )

    return {
        "success": all_required_passed,
        "results": results,
        "errors": errors,
        "completed": completed,
        "total": len(stages),
    }
