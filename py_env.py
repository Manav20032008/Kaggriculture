import sys


def get_kaggle_python():
    """Interpreter used to run matches. On a server, reuse the current one."""
    return sys.executable
