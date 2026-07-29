import atexit
import os
import shutil
import tempfile
from pathlib import Path


_TEST_STORAGE_DIRECTORY = Path(tempfile.mkdtemp(prefix="industrial-control-agent-tests-"))
os.environ["PLAN_STORAGE_PATH"] = str(_TEST_STORAGE_DIRECTORY / "plans.db")
os.environ["APP_ENV"] = "test"
os.environ["AUTH_MODE"] = "disabled"
atexit.register(shutil.rmtree, _TEST_STORAGE_DIRECTORY, ignore_errors=True)
