"""Tests for the project unittest entrypoint."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import run_tests


class RunTestsEntrypointTest(unittest.TestCase):
    def test_default_prefers_codex_bundled_python_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled_python = Path(temp_dir) / "python3"
            bundled_python.write_text("#!/bin/sh\n", encoding="utf-8")
            with mock.patch.object(run_tests, "DEFAULT_CODEX_PYTHON", bundled_python):
                with mock.patch.object(run_tests.sys, "executable", "/usr/bin/python3"):
                    with mock.patch.dict(run_tests.os.environ, {}, clear=True):
                        self.assertEqual(str(bundled_python), run_tests.resolve_test_python())

    def test_environment_override_wins_over_bundled_python(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled_python = Path(temp_dir) / "python3"
            bundled_python.write_text("#!/bin/sh\n", encoding="utf-8")
            with mock.patch.object(run_tests, "DEFAULT_CODEX_PYTHON", bundled_python):
                with mock.patch.dict(run_tests.os.environ, {"VDS_PYTHON_BIN": "/custom/python3"}, clear=True):
                    self.assertEqual("/custom/python3", run_tests.resolve_test_python())


if __name__ == "__main__":
    unittest.main()
