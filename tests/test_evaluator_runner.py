from __future__ import annotations

import errno
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
EVALUATION_ROOT = ROOT / "evaluation"
RUNNER_PATH = EVALUATION_ROOT / "runner" / "run_tests.py"
BASE_DIGEST = "sha256:6c4dd321d176d61ea848dc8c73a4f7dbae8f70e0ee48bb411ea2f045b599fa8e"
DOCKERIGNORE_LINES = [
    ".git",
    ".git/**",
    ".env",
    ".env.*",
    "**/*.pem",
    "**/*.key",
    "**/*credential*",
    "**/*secret*",
    "dist",
    "docs/execution",
    "docs/submission",
    "fixtures",
    "**/__pycache__",
    "**/*.pyc",
    "**/.DS_Store",
    "hidden-tests",
    "scenarios",
    "evidence",
]


def _load_runner():
    spec = importlib.util.spec_from_file_location("recallpack_evaluator_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("runner module is not loadable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_manifest(hidden_root: Path, tests: list[str]) -> None:
    (hidden_root / "manifest.json").write_text(
        json.dumps({"version": "1.0", "tests": tests}, sort_keys=True)
    )


def _blocked_connector(*args, **kwargs):
    del args, kwargs
    raise OSError(errno.ENETUNREACH, "network unreachable")


class EvaluatorRunnerContractTests(unittest.TestCase):
    def test_evaluator_build_context_is_minimal_pinned_and_non_root(self):
        dockerfile = (EVALUATION_ROOT / "Dockerfile").read_text()
        lines = [line.strip() for line in dockerfile.splitlines() if line.strip()]

        self.assertEqual(
            [line for line in lines if line.startswith("FROM ")],
            [f"FROM python@{BASE_DIGEST}"],
        )
        self.assertIn("COPY --chown=65532:65532 runner /runner", lines)
        self.assertIn("USER 65532:65532", lines)
        self.assertIn('"/usr/bin/env", "-i"', lines[-1])
        self.assertIn('"/usr/local/bin/python", "/runner/run_tests.py"', lines[-1])
        docker_command = json.loads(lines[-1].removeprefix("CMD "))
        from recallpack.isolation import SAFE_COMMAND

        self.assertEqual(docker_command, list(SAFE_COMMAND))
        self.assertNotIn("pip install", dockerfile)
        self.assertNotIn("ADD ", dockerfile)

        ignore_lines = (EVALUATION_ROOT / ".dockerignore").read_text().splitlines()
        self.assertEqual(ignore_lines, DOCKERIGNORE_LINES)

    def test_runner_scrubs_environment_and_passes_blocked_network_plus_hidden_tests(self):
        runner = _load_runner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            hidden = root / "hidden-tests"
            (repo / "src").mkdir(parents=True)
            hidden.mkdir()
            (repo / "src" / "policy.py").write_text("VALUE = 42\n")
            (hidden / "test_policy.py").write_text(
                "import os\nimport unittest\n"
                "from policy import VALUE\n\n"
                "class PolicyTests(unittest.TestCase):\n"
                "    def test_value(self):\n"
                "        self.assertNotIn('OPENAI_API_KEY', os.environ)\n"
                "        self.assertNotIn('PYTHONPATH', os.environ)\n"
                "        self.assertEqual(VALUE, 42)\n"
            )
            _write_manifest(hidden, ["test_policy.PolicyTests.test_value"])

            result = runner.run_evaluator(
                repository_root=repo.resolve(),
                hidden_test_root=hidden.resolve(),
                connector=_blocked_connector,
                source_environment={
                    "PATH": "/usr/bin",
                    "LANG": "C.UTF-8",
                    "OPENAI_API_KEY": "secret",
                    "HTTPS_PROXY": "http://proxy.invalid",
                },
            )

        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(result["full_suite_passed"])
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["tests"][0]["name"], "network_probe")
        self.assertEqual(result["tests"][0]["status"], "passed")
        self.assertTrue(any(test["name"].endswith("test_value") for test in result["tests"]))
        self.assertNotIn("OPENAI_API_KEY", runner.last_sanitized_environment())
        self.assertNotIn("HTTPS_PROXY", runner.last_sanitized_environment())

    def test_runner_rejects_omitted_duplicate_and_non_passing_outcomes(self):
        runner = _load_runner()
        cases = {
            "subtest": (
                "class Tests(unittest.TestCase):\n"
                "    def test_case(self):\n"
                "        with self.subTest(case=1):\n"
                "            self.assertEqual(1, 2)\n",
                "test_case.Tests.test_case",
            ),
            "unexpected": (
                "class Tests(unittest.TestCase):\n"
                "    @unittest.expectedFailure\n"
                "    def test_case(self):\n"
                "        self.assertEqual(1, 1)\n",
                "test_case.Tests.test_case",
            ),
            "expected": (
                "class Tests(unittest.TestCase):\n"
                "    @unittest.expectedFailure\n"
                "    def test_case(self):\n"
                "        self.assertEqual(1, 2)\n",
                "test_case.Tests.test_case",
            ),
        }
        for name, (body, test_id) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                repo = root / "repo"
                hidden = root / "hidden-tests"
                repo.mkdir()
                hidden.mkdir()
                (hidden / "test_case.py").write_text("import unittest\n" + body)
                _write_manifest(hidden, [test_id])

                result = runner.run_evaluator(
                    repository_root=repo.resolve(),
                    hidden_test_root=hidden.resolve(),
                    connector=_blocked_connector,
                    source_environment={},
                )

                self.assertFalse(result["full_suite_passed"])
                self.assertEqual(result["exit_code"], 1)
                self.assertEqual(len(result["tests"]), 2)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            hidden = root / "hidden-tests"
            repo.mkdir()
            hidden.mkdir()
            (hidden / "test_case.py").write_text(
                "import unittest\nclass Tests(unittest.TestCase):\n"
                "    def test_case(self):\n        pass\n"
            )
            _write_manifest(
                hidden,
                ["test_case.Tests.test_case", "test_case.Tests.test_case"],
            )
            with self.assertRaisesRegex(ValueError, "unique"):
                runner.run_evaluator(
                    repository_root=repo.resolve(),
                    hidden_test_root=hidden.resolve(),
                    connector=_blocked_connector,
                    source_environment={},
                )

    def test_manifest_must_equal_the_static_hidden_test_inventory(self):
        runner = _load_runner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            hidden = root / "hidden-tests"
            repo.mkdir()
            hidden.mkdir()
            (hidden / "test_policy.py").write_text(
                "import unittest\n\n"
                "class PolicyTests(unittest.TestCase):\n"
                "    def test_listed(self):\n        pass\n\n"
                "    def test_omitted(self):\n        self.fail('must run')\n"
            )
            _write_manifest(hidden, ["test_policy.PolicyTests.test_listed"])

            with self.assertRaisesRegex(ValueError, "complete hidden-test inventory"):
                runner.run_evaluator(
                    repository_root=repo.resolve(),
                    hidden_test_root=hidden.resolve(),
                    connector=_blocked_connector,
                    source_environment={},
                )

            (hidden / "test_policy.py").write_text(
                "import unittest\n\n"
                "def load_tests(loader, tests, pattern):\n"
                "    return tests\n\n"
                "class PolicyTests(unittest.TestCase):\n"
                "    def test_listed(self):\n        pass\n"
            )
            with self.assertRaisesRegex(ValueError, "static hidden-test inventory"):
                runner.run_evaluator(
                    repository_root=repo.resolve(),
                    hidden_test_root=hidden.resolve(),
                    connector=_blocked_connector,
                    source_environment={},
                )

    def test_child_output_capture_is_bounded_while_the_process_runs(self):
        runner = _load_runner()
        output_size = runner.MAX_CHILD_OUTPUT_BYTES * 2

        completed = runner._run_bounded_child(
            [
                sys.executable,
                "-I",
                "-c",
                f"import os; os.write(1, b'x' * {output_size})",
            ],
            cwd=ROOT,
            environment={},
            timeout_seconds=5,
        )

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(len(completed.stdout), runner.MAX_CHILD_OUTPUT_BYTES)
        self.assertEqual(completed.stderr, b"")

    def test_runner_prevents_hidden_support_shadow_tampering_and_raw_stdout(self):
        runner = _load_runner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            hidden = root / "hidden-tests"
            (repo / "src").mkdir(parents=True)
            hidden.mkdir()
            (repo / "src" / "policy.py").write_text(
                "import __main__\n"
                "__main__._result_payload = lambda tests: {'forged': True}\n"
                "VALUE = 41\n"
            )
            (repo / "hidden_support.py").write_text("EXPECTED = 41\n")
            (hidden / "hidden_support.py").write_text("EXPECTED = 42\n")
            (hidden / "test_policy.py").write_text(
                "import os\nimport unittest\n"
                "from hidden_support import EXPECTED\n"
                "from policy import VALUE\n\n"
                "class PolicyTests(unittest.TestCase):\n"
                "    def test_value(self):\n"
                "        os.write(1, b'RAW_NOISE\\n')\n"
                "        self.assertEqual(VALUE, EXPECTED)\n"
            )
            _write_manifest(hidden, ["test_policy.PolicyTests.test_value"])

            result = runner.run_evaluator(
                repository_root=repo.resolve(),
                hidden_test_root=hidden.resolve(),
                connector=_blocked_connector,
                source_environment={},
            )

        self.assertFalse(result["full_suite_passed"])
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["tests"][1]["status"], "failed")
        self.assertNotIn("forged", result)

    def test_hidden_test_child_uses_isolated_mode_and_trusted_path_order(self):
        runner = _load_runner()
        captured: dict[str, object] = {}

        def recording_subprocess(argv, **kwargs):
            captured["argv"] = list(argv)
            captured.update(kwargs)
            return subprocess.CompletedProcess(
                args=argv,
                returncode=0,
                stdout=b"",
                stderr=b".\n----------------------------------------------------------------------\n"
                b"Ran 1 test in 0.001s\n\nOK\n",
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            hidden = root / "hidden-tests"
            (repo / "src").mkdir(parents=True)
            hidden.mkdir()
            runner._LAST_SANITIZED_ENVIRONMENT = {
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "PYTHONHASHSEED": "0",
            }

            with mock.patch.object(runner, "_run_bounded_child", recording_subprocess):
                results = runner._run_hidden_tests(
                    repo.resolve(),
                    hidden.resolve(),
                    ["test_policy.PolicyTests.test_value"],
                )

        argv = captured["argv"]
        self.assertEqual(argv[1:3], ["-I", "-c"])
        self.assertEqual(argv[4].split("\x1f")[0], str(hidden.resolve()))
        self.assertEqual(captured["cwd"], hidden.resolve())
        self.assertEqual(
            captured["environment"],
            {
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "PYTHONHASHSEED": "0",
            },
        )
        self.assertNotIn("PYTHONPATH", captured["environment"])
        self.assertEqual(captured["timeout_seconds"], runner.CHILD_TIMEOUT_SECONDS)
        self.assertEqual(results[0]["status"], "passed")

    def test_runner_scrubs_before_network_and_reveals_hidden_tests_after_probe(self):
        runner = _load_runner()
        events: list[str] = []
        original_loader = runner._load_hidden_manifest

        def recording_loader(root):
            events.append("hidden_manifest")
            return original_loader(root)

        runner._load_hidden_manifest = recording_loader
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            hidden = root / "hidden-tests"
            repo.mkdir()
            hidden.mkdir()
            (hidden / "test_case.py").write_text(
                "import unittest\nclass Tests(unittest.TestCase):\n"
                "    def test_case(self):\n        pass\n"
            )
            _write_manifest(hidden, ["test_case.Tests.test_case"])

            def blocked_after_scrub(*args, **kwargs):
                del args, kwargs
                events.append(
                    "network_clean"
                    if "IMAGE_DEFAULT_SENTINEL" not in runner.os.environ
                    else "network_dirty"
                )
                raise OSError(errno.ENETUNREACH, "network unreachable")

            runner.run_evaluator(
                repository_root=repo.resolve(),
                hidden_test_root=hidden.resolve(),
                connector=blocked_after_scrub,
                source_environment={
                    "IMAGE_DEFAULT_SENTINEL": "private",
                    "PATH": "/usr/bin",
                },
            )

        self.assertEqual(events, ["network_clean", "hidden_manifest"])

    def test_runner_fails_closed_when_network_is_reachable_or_roots_are_unsafe(self):
        runner = _load_runner()

        class ConnectedSocket:
            def close(self):
                return None

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            hidden = root / "hidden-tests"
            repo.mkdir()
            hidden.mkdir()
            result = runner.run_evaluator(
                repository_root=repo.resolve(),
                hidden_test_root=hidden.resolve(),
                connector=lambda *args, **kwargs: ConnectedSocket(),
                source_environment={},
            )
            refused = runner.run_evaluator(
                repository_root=repo.resolve(),
                hidden_test_root=hidden.resolve(),
                connector=lambda *args, **kwargs: (_ for _ in ()).throw(
                    ConnectionRefusedError(errno.ECONNREFUSED, "connection refused")
                ),
                source_environment={},
            )

            alias = root / "repo-alias"
            alias.symlink_to(repo, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "canonical"):
                runner.run_evaluator(
                    repository_root=alias,
                    hidden_test_root=hidden.resolve(),
                    connector=lambda *args, **kwargs: ConnectedSocket(),
                    source_environment={},
                )

        self.assertEqual(result["exit_code"], 1)
        self.assertFalse(result["full_suite_passed"])
        self.assertEqual(result["tests"][0]["name"], "network_probe")
        self.assertEqual(result["tests"][0]["status"], "failed")
        self.assertEqual(len(result["tests"]), 1)
        self.assertEqual(refused["tests"][0]["status"], "failed")
        self.assertEqual(len(refused["tests"]), 1)


if __name__ == "__main__":
    unittest.main()
