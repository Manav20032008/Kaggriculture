"""Resolve the Python interpreter used to run Kaggriculture evaluations."""

import importlib.util
import os
from pathlib import Path
import shutil
import sys


def get_kaggle_python() -> str:
    """Prefer the current environment, then configured and project interpreters."""
    root = Path(__file__).resolve().parent
    if importlib.util.find_spec("kaggle_environments") is not None:
        return sys.executable

    configured = os.environ.get("NEURAL_COLISEUM_PYTHON") or os.environ.get("KAGGRI_PYTHON")
    candidates = (
        Path(configured).expanduser() if configured else None,
        root / "NITW_Farm_AI_Challenge_v2_Web" / ".venv" / "Scripts" / "python.exe",
        root / "NITW_Farm_AI_Challenge_v2_Web" / ".venv" / "bin" / "python",
        root / ".venv" / "Scripts" / "python.exe",
        root / ".venv" / "bin" / "python",
        Path(shutil.which("python3") or "") if shutil.which("python3") else None,
        Path(shutil.which("python") or "") if shutil.which("python") else None,
    )
    for candidate in candidates:
        if candidate and candidate.is_file():
            try:
                import subprocess
                result = subprocess.run(
                    [str(candidate), "-c", "import kaggle_environments"],
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
                if result.returncode == 0:
                    return str(candidate)
            except (OSError, subprocess.SubprocessError):
                continue
    return sys.executable
