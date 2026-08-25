import atexit
import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TEST_STORAGE_DIRECTORY = Path(tempfile.mkdtemp(prefix="industrial-control-agent-tests-"))
os.environ["PLAN_STORAGE_PATH"] = str(_TEST_STORAGE_DIRECTORY / "plans.db")
os.environ["APP_ENV"] = "test"
os.environ["AUTH_MODE"] = "disabled"
atexit.register(shutil.rmtree, _TEST_STORAGE_DIRECTORY, ignore_errors=True)


@pytest.fixture(autouse=True)
def reset_legacy_traffic_control_state() -> None:
    """Keep the standalone traffic-control module isolated between tests."""
    from backend.traffic_control import reset_rate_limiter

    reset_rate_limiter()
