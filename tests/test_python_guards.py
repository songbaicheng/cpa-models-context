"""Check assertion-based scripts fail before side effects under optimization."""
import pathlib
import subprocess
import sys
import unittest


class OptimizedExecutionTests(unittest.TestCase):
    def test_scripts_reject_optimized_python(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        for script in (root / "harness.py", root / "tests" / "integration.py"):
            for flag in ("-O", "-OO"):
                with self.subTest(script=script.name, flag=flag):
                    # No arguments: guards must run before argument parsing,
                    # loading a library, writing config, or invoking Docker.
                    result = subprocess.run(
                        [sys.executable, flag, str(script)],
                        capture_output=True, text=True, check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("requires Python assertions", result.stderr)
                    self.assertNotIn("PASS", result.stdout)
                    self.assertNotIn("checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
