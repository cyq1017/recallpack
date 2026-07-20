import importlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.v4_evidence_fixtures import ENV_ALLOWLIST, build_evaluator_contract


def _evaluator_contract() -> dict[str, object]:
    return build_evaluator_contract()


def _import_isolation():
    return importlib.import_module("recallpack.isolation")


def _safe_command() -> list[str]:
    return list(_import_isolation().SAFE_COMMAND)


class DownstreamIsolationRedTests(unittest.TestCase):
    def test_exact_docker_argv_env_allowlist_mounts_and_limits(self):
        contract = _evaluator_contract()
        self.assertEqual(
            contract["environment_allowlist"],
            ENV_ALLOWLIST,
        )
        self.assertEqual(
            contract["resource_limits"],
            {
                "cpus": 1,
                "memory_bytes": 1073741824,
                "pids": 128,
                "wall_timeout_seconds": 120,
                "tmpfs_size_bytes": 67108864,
            },
        )
        self.assertEqual(
            contract["execution_user"],
            {
                "username": "recallpack",
                "uid": 65532,
                "gid": 65532,
                "non_root": True,
            },
        )
        self.assertEqual(
            contract["isolation_flags"],
            {
                "network": "none",
                "read_only_root": True,
                "drop_all_capabilities": True,
                "no_new_privileges": True,
                "docker_socket_mounted": False,
                "tmp_is_tmpfs": True,
                "repository_mount_mode": "rw",
                "hidden_test_mount_mode": "ro",
            },
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            repo_root = root / "repo"
            hidden_root = root / "hidden-tests"
            repo_root.mkdir()
            hidden_root.mkdir()

            isolation = _import_isolation()
            roots = isolation.resolve_host_roots(
                {
                    "RECALLPACK_EVALUATOR_REPO_ROOT": str(repo_root),
                    "RECALLPACK_EVALUATOR_HIDDEN_TEST_ROOT": str(hidden_root),
                }
            )
            argv, env = isolation.build_docker_argv(
                evaluator_contract=contract,
                image_digest=contract["image_digest"],
                repository_root=roots.repository_root,
                hidden_test_root=roots.hidden_test_root,
                command=_safe_command(),
                container_name="recallpack-eval-test",
            )

        self.assertEqual(
            argv,
            [
                "docker",
                "run",
                "--rm",
                "--name",
                "recallpack-eval-test",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--user",
                "65532:65532",
                "--cpus",
                "1",
                "--memory",
                "1073741824",
                "--pids-limit",
                "128",
                "--tmpfs",
                "/tmp:size=67108864",
                "--mount",
                f"type=bind,src={repo_root},dst=/workspace/repo,readonly=false",
                "--mount",
                f"type=bind,src={hidden_root},dst=/workspace/hidden-tests,readonly=true",
                "-e",
                "HOME",
                "-e",
                "HOSTNAME",
                "-e",
                "LANG",
                "-e",
                "LC_ALL",
                "-e",
                "PATH",
                "-e",
                "PYTHONHASHSEED",
                "-e",
                "PYTHONDONTWRITEBYTECODE",
                contract["image_digest"],
                "/usr/bin/env",
                "-i",
                "HOME=/tmp",
                "HOSTNAME=recallpack-evaluator",
                "LANG=C.UTF-8",
                "LC_ALL=C.UTF-8",
                "PATH=/usr/local/bin:/usr/bin:/bin",
                "PYTHONHASHSEED=0",
                "PYTHONDONTWRITEBYTECODE=1",
                "/usr/local/bin/python",
                "/runner/run_tests.py",
            ],
        )
        self.assertEqual(set(env), set(contract["environment_allowlist"]))

    def test_runner_receives_only_allowlisted_environment_without_inheritance(self):
        contract = _evaluator_contract()
        inherited_env = {
            "HOME": "/tmp/home",
            "HOSTNAME": "recallpack-test",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/bin",
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "HTTP_PROXY": "http://proxy.local",
            "HTTPS_PROXY": "http://proxy.local",
            "ALL_PROXY": "http://proxy.local",
            "AWS_SECRET_ACCESS_KEY": "secret",
            "OPENAI_API_KEY": "secret",
        }

        class CapturingRunner:
            def __call__(self, argv, *, env, timeout, capture_output, text, check):
                del argv, timeout, capture_output, text, check
                self.env = dict(env)
                return subprocess.CompletedProcess(
                    args=["docker"],
                    returncode=0,
                    stdout=(
                        '{"tests":[{"name":"network_probe","status":"passed",'
                        '"duration_ms":5,"evidence_artifact_id":"stdout_network"},'
                        '{"name":"test_policy","status":"passed",'
                        '"duration_ms":3,"evidence_artifact_id":"runner_result_json"}],'
                        '"full_suite_passed":true,"passed":2,"failed":0,'
                        '"exit_code":0,"timed_out":false}'
                    ),
                    stderr="",
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            repo_root = root / "repo"
            hidden_root = root / "hidden-tests"
            repo_root.mkdir()
            hidden_root.mkdir()

            runner = CapturingRunner()
            isolation = _import_isolation()
            isolation.run_isolated_suite(
                evaluator_contract=contract,
                image_digest=contract["image_digest"],
                repository_root=repo_root,
                hidden_test_root=hidden_root,
                command=_safe_command(),
                docker_runner=runner,
                inherited_env=inherited_env,
            )

        self.assertEqual(sorted(runner.env), sorted(ENV_ALLOWLIST))
        self.assertEqual(
            runner.env,
            {
                "HOME": "/tmp",
                "HOSTNAME": "recallpack-evaluator",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "PYTHONHASHSEED": "0",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        self.assertNotIn("HTTP_PROXY", runner.env)
        self.assertNotIn("HTTPS_PROXY", runner.env)
        self.assertNotIn("ALL_PROXY", runner.env)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", runner.env)
        self.assertNotIn("OPENAI_API_KEY", runner.env)

    def test_realpath_identity_rejects_symlinked_or_duplicate_roots(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            repo_root = root / "repo"
            hidden_root = root / "hidden-tests"
            alias_root = root / "repo-alias"
            repo_root.mkdir()
            hidden_root.mkdir()
            alias_root.symlink_to(repo_root, target_is_directory=True)

            self.assertNotEqual(str(alias_root), str(alias_root.resolve()))
            self.assertTrue(repo_root.resolve().is_absolute())
            self.assertTrue(hidden_root.resolve().is_absolute())

            isolation = _import_isolation()
            with self.assertRaisesRegex(ValueError, "realpath"):
                isolation.resolve_host_roots(
                    {
                        "RECALLPACK_EVALUATOR_REPO_ROOT": str(alias_root),
                        "RECALLPACK_EVALUATOR_HIDDEN_TEST_ROOT": str(hidden_root),
                    }
                )
            with self.assertRaisesRegex(ValueError, "distinct"):
                isolation.resolve_host_roots(
                    {
                        "RECALLPACK_EVALUATOR_REPO_ROOT": str(repo_root),
                        "RECALLPACK_EVALUATOR_HIDDEN_TEST_ROOT": str(repo_root),
                    }
                )

    def test_blocked_network_probe_and_output_capture_are_recorded(self):
        contract = _evaluator_contract()

        class FakeRunner:
            def __call__(self, argv, *, env, timeout, capture_output, text, check):
                del argv, env, timeout, capture_output, text, check
                return subprocess.CompletedProcess(
                    args=["docker"],
                    returncode=0,
                    stdout=(
                        '{"tests":[{"name":"network_probe","status":"passed",'
                        '"duration_ms":7,"evidence_artifact_id":"stdout_network"},'
                        '{"name":"test_policy","status":"passed",'
                        '"duration_ms":3,"evidence_artifact_id":"runner_result_json"}],'
                        '"full_suite_passed":true,"passed":2,"failed":0,'
                        '"exit_code":0,"timed_out":false}'
                    ),
                    stderr="",
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            repo_root = root / "repo"
            hidden_root = root / "hidden-tests"
            repo_root.mkdir()
            hidden_root.mkdir()

            isolation = _import_isolation()
            result = isolation.run_isolated_suite(
                evaluator_contract=contract,
                image_digest=contract["image_digest"],
                repository_root=repo_root,
                hidden_test_root=hidden_root,
                command=_safe_command(),
                docker_runner=FakeRunner(),
            )

        self.assertEqual(result.exit_code, 0)
        self.assertFalse(result.timed_out)
        self.assertEqual(result.stdout, '{"tests":[{"name":"network_probe","status":"passed","duration_ms":7,"evidence_artifact_id":"stdout_network"},{"name":"test_policy","status":"passed","duration_ms":3,"evidence_artifact_id":"runner_result_json"}],"full_suite_passed":true,"passed":2,"failed":0,"exit_code":0,"timed_out":false}')
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.json_result["tests"][0]["name"], "network_probe")
        self.assertEqual(result.json_result["tests"][0]["status"], "passed")

    def test_malformed_runner_json_and_network_probe_success_fail_closed(self):
        contract = _evaluator_contract()

        class MalformedJsonRunner:
            def __call__(self, argv, *, env, timeout, capture_output, text, check):
                del argv, env, timeout, capture_output, text, check
                return subprocess.CompletedProcess(
                    args=["docker"],
                    returncode=1,
                    stdout="{not-json",
                    stderr="broken",
                )

        class NetworkProbeSkippedRunner:
            def __call__(self, argv, *, env, timeout, capture_output, text, check):
                del argv, env, timeout, capture_output, text, check
                return subprocess.CompletedProcess(
                    args=["docker"],
                    returncode=1,
                    stdout=(
                        '{"tests":[{"name":"network_probe","status":"skipped",'
                        '"duration_ms":5,"evidence_artifact_id":"stdout_network"}],'
                        '"full_suite_passed":false,"passed":0,"failed":0,'
                        '"exit_code":1,"timed_out":false}'
                    ),
                    stderr="",
                )

        class NetworkOnlyPassedRunner:
            def __call__(self, argv, *, env, timeout, capture_output, text, check):
                del argv, env, timeout, capture_output, text, check
                return subprocess.CompletedProcess(
                    args=["docker"],
                    returncode=0,
                    stdout=(
                        '{"tests":[{"name":"network_probe","status":"passed",'
                        '"duration_ms":5,"evidence_artifact_id":"stdout_network"}],'
                        '"full_suite_passed":true,"passed":1,"failed":0,'
                        '"exit_code":0,"timed_out":false}'
                    ),
                    stderr="",
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            repo_root = root / "repo"
            hidden_root = root / "hidden-tests"
            repo_root.mkdir()
            hidden_root.mkdir()

            isolation = _import_isolation()

            with self.assertRaisesRegex(ValueError, "invalid_test_result"):
                isolation.run_isolated_suite(
                    evaluator_contract=contract,
                    image_digest=contract["image_digest"],
                    repository_root=repo_root,
                    hidden_test_root=hidden_root,
                    command=_safe_command(),
                    docker_runner=MalformedJsonRunner(),
                )
            with self.assertRaisesRegex(
                ValueError,
                "invalid_test_result|invalid_sandbox_evidence",
            ):
                isolation.run_isolated_suite(
                    evaluator_contract=contract,
                    image_digest=contract["image_digest"],
                    repository_root=repo_root,
                    hidden_test_root=hidden_root,
                    command=_safe_command(),
                    docker_runner=NetworkProbeSkippedRunner(),
                )
            with self.assertRaisesRegex(ValueError, "invalid_test_result"):
                isolation.run_isolated_suite(
                    evaluator_contract=contract,
                    image_digest=contract["image_digest"],
                    repository_root=repo_root,
                    hidden_test_root=hidden_root,
                    command=_safe_command(),
                    docker_runner=NetworkOnlyPassedRunner(),
                )

    def test_timeout_and_docker_unavailable_map_to_sandbox_failures_only(self):
        contract = _evaluator_contract()

        class TimeoutRunner:
            def __call__(self, argv, *, env, timeout, capture_output, text, check):
                raise subprocess.TimeoutExpired(argv, timeout)

        class MissingDockerRunner:
            def __call__(self, argv, *, env, timeout, capture_output, text, check):
                raise FileNotFoundError("docker")

        class DaemonUnavailableRunner:
            def __call__(self, argv, *, env, timeout, capture_output, text, check):
                del env, timeout, capture_output, text, check
                return subprocess.CompletedProcess(
                    args=argv,
                    returncode=125,
                    stdout="",
                    stderr="Cannot connect to the Docker daemon",
                )

        class CleanupRunner:
            def __init__(self):
                self.calls = []

            def __call__(self, argv, **kwargs):
                self.calls.append((list(argv), dict(kwargs)))
                return subprocess.CompletedProcess(
                    args=argv,
                    returncode=0,
                    stdout="",
                    stderr="",
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            repo_root = root / "repo"
            hidden_root = root / "hidden-tests"
            repo_root.mkdir()
            hidden_root.mkdir()

            isolation = _import_isolation()

            cleanup_runner = CleanupRunner()
            timed_out = isolation.run_isolated_suite(
                evaluator_contract=contract,
                image_digest=contract["image_digest"],
                repository_root=repo_root,
                hidden_test_root=hidden_root,
                command=_safe_command(),
                docker_runner=TimeoutRunner(),
                docker_cleanup_runner=cleanup_runner,
            )
            unavailable = isolation.run_isolated_suite(
                evaluator_contract=contract,
                image_digest=contract["image_digest"],
                repository_root=repo_root,
                hidden_test_root=hidden_root,
                command=_safe_command(),
                docker_runner=MissingDockerRunner(),
            )
            daemon_unavailable = isolation.run_isolated_suite(
                evaluator_contract=contract,
                image_digest=contract["image_digest"],
                repository_root=repo_root,
                hidden_test_root=hidden_root,
                command=_safe_command(),
                docker_runner=DaemonUnavailableRunner(),
            )

        self.assertTrue(timed_out.blocked)
        self.assertEqual(timed_out.failure_code, "sandbox_timeout")
        self.assertFalse(timed_out.host_fallback_used)
        self.assertTrue(timed_out.cleanup_attempted)
        self.assertTrue(timed_out.cleanup_succeeded)
        self.assertEqual(len(cleanup_runner.calls), 1)
        cleanup_argv, cleanup_kwargs = cleanup_runner.calls[0]
        self.assertEqual(cleanup_argv[:3], ["docker", "rm", "-f"])
        self.assertEqual(cleanup_argv[3], timed_out.container_name)
        self.assertEqual(cleanup_kwargs["timeout"], 10)
        self.assertTrue(unavailable.blocked)
        self.assertEqual(unavailable.failure_code, "sandbox_unavailable")
        self.assertFalse(unavailable.host_fallback_used)
        self.assertFalse(unavailable.cleanup_attempted)
        self.assertTrue(daemon_unavailable.blocked)
        self.assertEqual(daemon_unavailable.failure_code, "sandbox_unavailable")
        self.assertIn("Docker daemon", daemon_unavailable.stderr)

    def test_reserved_docker_exit_code_cannot_be_disguised_as_suite_json(self):
        contract = _evaluator_contract()
        payload = {
            "tests": [
                {
                    "name": "network_probe",
                    "status": "passed",
                    "duration_ms": 1,
                    "evidence_artifact_id": "runner_result_json",
                },
                {
                    "name": "test_policy",
                    "status": "failed",
                    "duration_ms": 1,
                    "evidence_artifact_id": "runner_result_json",
                },
            ],
            "full_suite_passed": False,
            "passed": 1,
            "failed": 1,
            "exit_code": 125,
            "timed_out": False,
        }

        class JsonShapedDockerFailure:
            def __call__(self, argv, *, env, timeout, capture_output, text, check):
                del env, timeout, capture_output, text, check
                return subprocess.CompletedProcess(
                    args=argv,
                    returncode=125,
                    stdout=json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    stderr="Docker daemon failed after emitting stale stdout",
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            repo_root = root / "repo"
            hidden_root = root / "hidden-tests"
            repo_root.mkdir()
            hidden_root.mkdir()
            result = _import_isolation().run_isolated_suite(
                evaluator_contract=contract,
                image_digest=contract["image_digest"],
                repository_root=repo_root,
                hidden_test_root=hidden_root,
                command=_safe_command(),
                docker_runner=JsonShapedDockerFailure(),
            )

        self.assertTrue(result.blocked)
        self.assertEqual(result.failure_code, "sandbox_unavailable")
        self.assertIsNone(result.json_result)
        self.assertEqual(result.exit_code, 125)

    def test_timeout_cleanup_failure_is_a_hard_safety_error(self):
        contract = _evaluator_contract()

        class TimeoutRunner:
            def __call__(self, argv, *, env, timeout, capture_output, text, check):
                raise subprocess.TimeoutExpired(argv, timeout)

        class FailedCleanupRunner:
            def __call__(self, argv, **kwargs):
                del kwargs
                return subprocess.CompletedProcess(
                    args=argv,
                    returncode=1,
                    stdout="",
                    stderr="cleanup failed",
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            repo_root = root / "repo"
            hidden_root = root / "hidden-tests"
            repo_root.mkdir()
            hidden_root.mkdir()

            with self.assertRaisesRegex(RuntimeError, "sandbox_cleanup_failed"):
                _import_isolation().run_isolated_suite(
                    evaluator_contract=contract,
                    image_digest=contract["image_digest"],
                    repository_root=repo_root,
                    hidden_test_root=hidden_root,
                    command=_safe_command(),
                    docker_runner=TimeoutRunner(),
                    docker_cleanup_runner=FailedCleanupRunner(),
                )


if __name__ == "__main__":
    unittest.main()
