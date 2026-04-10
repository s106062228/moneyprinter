"""Tests for the retry and pipeline recovery module."""

import pytest
from unittest.mock import MagicMock, patch

from retry import retry, retry_call, PipelineStage, run_pipeline


class TestRetryDecorator:
    """Tests for the @retry decorator."""

    def test_succeeds_on_first_try(self):
        """Function that succeeds should return immediately."""
        call_count = 0

        @retry(max_retries=3)
        def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = succeed()
        assert result == "ok"
        assert call_count == 1

    def test_retries_on_failure_then_succeeds(self):
        """Function should retry and eventually succeed."""
        call_count = 0

        @retry(max_retries=3, base_delay=0.01)
        def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return "ok"

        result = fail_twice()
        assert result == "ok"
        assert call_count == 3

    def test_raises_after_max_retries(self):
        """Should raise the last exception after exhausting retries."""

        @retry(max_retries=2, base_delay=0.01)
        def always_fail():
            raise RuntimeError("always fails")

        with pytest.raises(RuntimeError, match="always fails"):
            always_fail()

    def test_only_retries_specified_exceptions(self):
        """Should not retry exceptions that aren't in retryable_exceptions."""

        @retry(max_retries=3, base_delay=0.01, retryable_exceptions=(ValueError,))
        def raise_type_error():
            raise TypeError("wrong type")

        with pytest.raises(TypeError):
            raise_type_error()

    def test_on_retry_callback_called(self):
        """on_retry callback should be called before each retry."""
        callback = MagicMock()
        call_count = 0

        @retry(max_retries=2, base_delay=0.01, on_retry=callback)
        def fail_once():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("fail")
            return "ok"

        fail_once()
        assert callback.call_count == 1

    def test_backoff_factor(self):
        """Delay should increase by backoff_factor each retry."""
        delays = []

        def track_delay(attempt, exc, delay):
            delays.append(delay)

        call_count = 0

        @retry(max_retries=3, base_delay=1.0, backoff_factor=2.0, max_delay=100.0, on_retry=track_delay)
        def fail_thrice():
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise ValueError("fail")
            return "ok"

        with patch("retry.time.sleep"):  # Don't actually sleep
            fail_thrice()

        assert len(delays) == 3
        assert delays[0] == 1.0
        assert delays[1] == 2.0
        assert delays[2] == 4.0

    def test_max_delay_cap(self):
        """Delay should not exceed max_delay."""
        delays = []

        def track_delay(attempt, exc, delay):
            delays.append(delay)

        call_count = 0

        @retry(max_retries=5, base_delay=10.0, backoff_factor=3.0, max_delay=25.0, on_retry=track_delay)
        def keep_failing():
            nonlocal call_count
            call_count += 1
            if call_count <= 5:
                raise ValueError("fail")
            return "ok"

        with patch("retry.time.sleep"):
            keep_failing()

        # All delays should be <= 25.0
        for d in delays:
            assert d <= 25.0


class TestRetryCall:
    """Tests for the retry_call function."""

    def test_successful_call(self):
        result = retry_call(lambda: 42)
        assert result == 42

    def test_call_with_args(self):
        def add(a, b):
            return a + b

        result = retry_call(add, args=(3, 4))
        assert result == 7

    def test_call_with_kwargs(self):
        def greet(name="World"):
            return f"Hello {name}"

        result = retry_call(greet, kwargs={"name": "Test"})
        assert result == "Hello Test"

    def test_retries_and_succeeds(self):
        state = {"count": 0}

        def fail_then_succeed():
            state["count"] += 1
            if state["count"] < 2:
                raise ConnectionError("down")
            return "up"

        with patch("retry.time.sleep"):
            result = retry_call(fail_then_succeed, max_retries=3, base_delay=0.01)

        assert result == "up"
        assert state["count"] == 2

    def test_raises_after_exhaustion(self):
        def always_fail():
            raise TimeoutError("timeout")

        with patch("retry.time.sleep"):
            with pytest.raises(TimeoutError):
                retry_call(always_fail, max_retries=1, base_delay=0.01)


class TestPipelineStage:
    """Tests for PipelineStage."""

    def test_successful_stage(self):
        stage = PipelineStage("test", lambda: "result", max_retries=0)
        assert stage.execute() is True
        assert stage.result == "result"
        assert stage.error is None

    def test_failed_required_stage(self):
        def fail():
            raise RuntimeError("broken")

        with patch("retry.time.sleep"):
            stage = PipelineStage("test", fail, max_retries=0, required=True)
            assert stage.execute() is False
            assert stage.error is not None

    def test_failed_optional_stage(self):
        def fail():
            raise RuntimeError("broken")

        with patch("retry.time.sleep"):
            stage = PipelineStage("test", fail, max_retries=0, required=False)
            assert stage.execute() is False


class TestRunPipeline:
    """Tests for the run_pipeline function."""

    def test_all_stages_succeed(self):
        stages = [
            PipelineStage("step1", lambda: "a", max_retries=0),
            PipelineStage("step2", lambda: "b", max_retries=0),
            PipelineStage("step3", lambda: "c", max_retries=0),
        ]

        result = run_pipeline(stages)
        assert result["success"] is True
        assert result["completed"] == 3
        assert result["total"] == 3
        assert result["results"] == {"step1": "a", "step2": "b", "step3": "c"}
        assert result["errors"] == {}

    def test_required_stage_failure_aborts(self):
        stages = [
            PipelineStage("step1", lambda: "a", max_retries=0),
            PipelineStage("step2", lambda: (_ for _ in ()).throw(RuntimeError("fail")), max_retries=0, required=True),
            PipelineStage("step3", lambda: "c", max_retries=0),
        ]

        with patch("retry.time.sleep"):
            result = run_pipeline(stages)

        assert result["success"] is False
        assert result["completed"] == 1  # only step1 completed
        assert "step2" in result["errors"]

    def test_optional_stage_failure_continues(self):
        stages = [
            PipelineStage("step1", lambda: "a", max_retries=0),
            PipelineStage("step2", lambda: (_ for _ in ()).throw(RuntimeError("fail")), max_retries=0, required=False),
            PipelineStage("step3", lambda: "c", max_retries=0),
        ]

        with patch("retry.time.sleep"):
            result = run_pipeline(stages)

        assert result["success"] is True  # all REQUIRED stages passed
        assert result["completed"] == 2  # step1 and step3
        assert "step2" in result["errors"]

    def test_empty_pipeline(self):
        result = run_pipeline([])
        assert result["success"] is True
        assert result["completed"] == 0
        assert result["total"] == 0
