import subprocess
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_main_imports_from_backend_working_directory() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import main; assert main.app"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
