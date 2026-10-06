import subprocess
import unittest
from unittest.mock import patch

from backend.services.sandbox import SandboxError, run_sandbox_source


class SandboxTests(unittest.TestCase):
    def test_timeout_is_reported_cleanly(self):
        with patch("backend.services.sandbox._run_local", side_effect=subprocess.TimeoutExpired("match", 120)):
            with self.assertRaisesRegex(SandboxError, "exceeded"):
                run_sandbox_source("def agent(obs): return {}", "balanced", 1, trusted_local=True)


if __name__ == "__main__":
    unittest.main()
