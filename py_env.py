import sys
import os
import shutil
import subprocess
from pathlib import Path

def get_kaggle_python() -> str:
    """
    Find and return the path to a Python interpreter that has kaggle_environments installed.
    Prefers sys.executable if it already works.
    Falls back to environment variables, known paths, and launcher queries.
    """
    # 1. Try sys.executable first (prefer propagation)
    try:
        import kaggle_environments
        return sys.executable
    except ImportError:
        pass

    # 2. Check explicit environment override
    env_override = os.environ.get("KAGGRI_PYTHON")
    if env_override and os.path.isfile(env_override):
        return env_override

    # 3. Known locations on this machine
    user_appdata_py313 = Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python313" / "python.exe"
    candidates = [
        str(user_appdata_py313),
        shutil.which("python3.13"),
        shutil.which("python3"),
        shutil.which("python"),
    ]

    for cand in candidates:
        if cand and os.path.isfile(cand):
            try:
                proc = subprocess.run(
                    [cand, "-c", "import kaggle_environments"],
                    capture_output=True,
                    timeout=5
                )
                if proc.returncode == 0:
                    return cand
            except Exception:
                continue

    # 4. Probe Windows 'py' launcher for 3.13
    py_cmd = shutil.which("py")
    if py_cmd:
        try:
            proc = subprocess.run(
                [py_cmd, "-3.13", "-c", "import sys; print(sys.executable)"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if proc.returncode == 0:
                exe = proc.stdout.strip()
                if exe and os.path.isfile(exe):
                    return exe
        except Exception:
            pass

    # Fallback to sys.executable
    return sys.executable

if __name__ == "__main__":
    resolved = get_kaggle_python()
    print("Resolved Python:", resolved)
    proc = subprocess.run([resolved, "-c", "import kaggle_environments; print('kaggle_environments found in:', kaggle_environments.__file__)"], capture_output=True, text=True)
    print("Test output:", proc.stdout.strip())
