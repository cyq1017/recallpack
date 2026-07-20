from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import mimetypes
import os
import re
import sqlite3
import tempfile
import uuid
from collections.abc import Iterator, Set
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from recallpack.artifacts import build_compile_bundle_v4, publish_compile_bundle_v4
from recallpack.compile import CompileRequest, CompileService
from recallpack.demo import build_demo_payload, discover_secondary_hero_fixture_roots
from recallpack.evaluation import load_hero_fixture
from recallpack.observe import ObserveRequest, ObserveRuntime
from recallpack.providers import (
    DeterministicKeywordEmbeddingProvider,
    DeterministicKeywordRerankProvider,
    FakeRuleBasedMemoryDecisionProvider,
    ProviderMemoryDecider,
    ProviderRanker,
)
from recallpack.storage import SqliteEventStore


_DEFAULT_COMPONENTS = ("retry", "auth", "cache", "config")
_COMPONENT_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_RUNTIME_NONCE = uuid.uuid4().hex


@dataclass(frozen=True)
class ComponentRegistry(Set[str]):
    values: tuple[str, ...]

    def __contains__(self, value: object) -> bool:
        return value in self.values

    def __iter__(self) -> Iterator[str]:
        return iter(self.values)

    def __len__(self) -> int:
        return len(self.values)


def build_component_registry(configured: str | None) -> ComponentRegistry:
    raw = configured or ""
    if len(raw.encode("utf-8")) > 4096:
        raise ValueError("component_bytes_limit")
    extensions = [part.strip() for part in raw.split(",") if part.strip()]
    combined = [*_DEFAULT_COMPONENTS, *extensions]
    if len(combined) > 64:
        raise ValueError("component_limit")
    if len(set(combined)) != len(combined):
        raise ValueError("duplicate_component")
    if any(_COMPONENT_PATTERN.fullmatch(component) is None for component in combined):
        raise ValueError("invalid_component_name")
    if len(",".join(combined).encode("utf-8")) > 4096:
        raise ValueError("component_bytes_limit")
    return ComponentRegistry(tuple(combined))


@dataclass(frozen=True)
class RuntimeComposition:
    component_registry: ComponentRegistry

    @property
    def demo_components(self) -> ComponentRegistry:
        return self.component_registry

    @property
    def evaluator_components(self) -> ComponentRegistry:
        return self.component_registry

    def create_observe_runtime(self, store: Any, decider: Any) -> ObserveRuntime:
        return ObserveRuntime(
            store=store,
            decider=decider,
            components=self.component_registry,
        )

    def create_compile_service(
        self,
        store: Any,
        ranker: Any,
        embedding_provider: Any,
        retrieval_top_n: int = 8,
    ) -> CompileService:
        return CompileService(
            store=store,
            ranker=ranker,
            embedding_provider=embedding_provider,
            retrieval_top_n=retrieval_top_n,
            components=self.component_registry,
        )


def create_runtime_composition(
    component_registry: ComponentRegistry | None = None,
) -> RuntimeComposition:
    registry = component_registry or build_component_registry(
        os.environ.get("RECALLPACK_COMPONENTS")
    )
    return RuntimeComposition(registry)


_STARTUP_COMPOSITION = create_runtime_composition()


@dataclass(frozen=True)
class DemoResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes


def handle_demo_request(
    method: str,
    path: str,
    body: bytes,
    project_root: str | Path | None = None,
    composition: RuntimeComposition | None = None,
) -> DemoResponse:
    root = Path(project_root) if project_root is not None else _default_project_root()
    runtime = composition or _STARTUP_COMPOSITION
    route = urlparse(path).path
    if method == "GET" and route == "/api/demo":
        return _json_response(200, _demo_payload(root))
    if method == "GET" and route == "/api/health":
        return _json_response(200, _health_payload(root))
    if method == "POST" and route == "/compile":
        return _compile_response(root, body, runtime)
    if method == "POST" and route == "/observe":
        return _observe_response(root, body, runtime)
    return _json_response(404, {"error": "not_found"})


class RecallPackDemoHandler(BaseHTTPRequestHandler):
    project_root: Path | None = None
    runtime_composition: RuntimeComposition = _STARTUP_COMPOSITION

    def do_GET(self) -> None:
        root = self.project_root or _default_project_root()
        response = handle_demo_request(
            "GET", self.path, b"", root, self.runtime_composition
        )
        if response.status_code != 404:
            self._send(response)
            return
        static_response = _static_response(root, self.path)
        self._send(static_response)

    def do_POST(self) -> None:
        root = self.project_root or _default_project_root()
        try:
            length = int(self.headers.get("content-length", "0"))
        except ValueError:
            self._send(_json_response(400, {"error": "invalid_content_length"}))
            return
        body = self.rfile.read(length)
        self._send(
            handle_demo_request(
                "POST", self.path, body, root, self.runtime_composition
            )
        )

    def do_HEAD(self) -> None:
        root = self.project_root or _default_project_root()
        response = handle_demo_request(
            "GET", self.path, b"", root, self.runtime_composition
        )
        if response.status_code == 404:
            response = _static_response(root, self.path)
        self._send_headers(response)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send(self, response: DemoResponse) -> None:
        self._send_headers(response)
        self.wfile.write(response.body)

    def _send_headers(self, response: DemoResponse) -> None:
        self.send_response(response.status_code)
        for name, value in response.headers.items():
            self.send_header(name, value)
        self.end_headers()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8789)
    parser.add_argument("--root", type=Path, default=_default_project_root())
    args = parser.parse_args(argv)
    server = create_demo_server(args.host, args.port, args.root)
    server.serve_forever()


def create_demo_server(
    host: str,
    port: int,
    root: Path,
    composition: RuntimeComposition | None = None,
) -> HTTPServer:
    handler_class = type(
        "BoundRecallPackDemoHandler",
        (RecallPackDemoHandler,),
        {
            "project_root": root,
            "runtime_composition": composition or _STARTUP_COMPOSITION,
        },
    )
    return ThreadingHTTPServer((host, port), handler_class)


def _compile_response(
    root: Path, body: bytes, composition: RuntimeComposition
) -> DemoResponse:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _compile_error_response(400, "invalid_json")
    if not isinstance(payload, dict) or set(payload) != {
        "project_id",
        "goal",
        "component",
        "budget_tokens",
    }:
        return _compile_error_response(400, "invalid_request")
    project_id = payload.get("project_id")
    goal = payload.get("goal")
    component = payload.get("component")
    budget_value = payload.get("budget_tokens")
    if (
        not isinstance(project_id, str)
        or not 1 <= len(project_id) <= 128
        or not isinstance(goal, str)
        or not 1 <= len(goal) <= 20_000
        or not isinstance(component, str)
        or not 1 <= len(component) <= 128
    ):
        return _compile_error_response(400, "invalid_request")
    if isinstance(budget_value, bool) or not isinstance(budget_value, int):
        return _compile_error_response(400, "invalid_budget")
    budget_tokens = budget_value
    db_path, db_path_source = _runtime_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path_source in {"env", "tempdir"}:
        store = SqliteEventStore(db_path)
        if project_id == "project-a" and db_path_source != "env":
            fixture = load_hero_fixture(root / "fixtures" / "project-a")
            _ensure_demo_fixture_seeded(store, fixture, composition)
        ranker = ProviderRanker(DeterministicKeywordRerankProvider())
        result = composition.create_compile_service(
            store=store,
            ranker=ranker,
            embedding_provider=DeterministicKeywordEmbeddingProvider(),
        ).compile(
            CompileRequest(
                project_id=project_id,
                goal=goal,
                component=component,
                budget_tokens=budget_tokens,
            )
        )
    else:
        return _json_response(500, {"error": "invalid_runtime_db_source"})
    trace = dict(result.trace)
    if result.status_code != 200:
        return _compile_error_response(
            result.status_code,
            result.error or "storage_failure",
        )

    compile_id = f"cmp_{uuid.uuid4().hex}"
    pack = {"memories": result.pack.memories}
    request_record = {
        "project_id": project_id,
        "goal": goal,
        "component": component,
        "budget_tokens": budget_tokens,
    }
    try:
        bundle = build_compile_bundle_v4(
            compile_id=compile_id,
            request=request_record,
            pack=pack,
            compile_trace=trace,
        )
        manifest = publish_compile_bundle_v4(
            bundle,
            artifact_root=_runtime_artifact_root(),
        )
    except ValueError as exc:
        error = (
            "artifact_publication_failed"
            if "artifact_publication_failed" in str(exc)
            else "artifact_validation_failed"
        )
        return _compile_error_response(503, error)

    artifact_by_name = {item["name"]: item for item in manifest["files"]}
    return _json_response(
        200,
        {
            "status_code": 200,
            "compile_id": compile_id,
            "pack": pack,
            "exact_token_count": bundle["trace"]["exact_token_count"],
            "tokenizer": bundle["trace"]["tokenizer"],
            "artifacts": {
                "recallpack_json": artifact_by_name["recallpack.json"],
                "pack_md": artifact_by_name["PACK.md"],
                "trace_json": artifact_by_name["trace.json"],
            },
            "trace": _compile_trace_summary(trace),
        },
    )


def _observe_response(
    root: Path, body: bytes, composition: RuntimeComposition
) -> DemoResponse:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _observe_error_response(400, "invalid_json")
    if not isinstance(payload, dict):
        return _observe_error_response(400, "invalid_request")
    request_or_error = _observe_request_from_payload(payload)
    if isinstance(request_or_error, str):
        return _observe_error_response(400, request_or_error)
    db_path, _ = _runtime_db_path()
    decider = _memory_decider()
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        store = SqliteEventStore(db_path)
    except sqlite3.Error as exc:
        error = (
            "sqlite_busy"
            if "locked" in str(exc).lower() or "busy" in str(exc).lower()
            else "sqlite_io_error"
        )
        return _json_response(
            503,
            {
                "status_code": 503,
                "error": error,
                "retryable": True,
                "run_id": "run_unavailable",
            },
        )
    response = composition.create_observe_runtime(store=store, decider=decider).observe(
        request_or_error,
        now=100 + request_or_error.sequence_no,
    )
    return _serialize_observe_response(request_or_error, response, decider)


def _observe_request_from_payload(payload: dict[str, Any]) -> ObserveRequest | str:
    if set(payload) != {
        "project_id",
        "session_id",
        "event_id",
        "sequence_no",
        "actor",
        "kind",
        "observed_at",
        "text",
    }:
        return "invalid_request"
    required_string_fields = (
        "project_id",
        "session_id",
        "event_id",
        "actor",
        "kind",
        "observed_at",
        "text",
    )
    if not all(isinstance(payload.get(field), str) for field in required_string_fields):
        return "invalid_request"
    if (
        not 1 <= len(payload["project_id"]) <= 128
        or not 1 <= len(payload["session_id"]) <= 128
        or not 1 <= len(payload["event_id"]) <= 128
        or payload["actor"] not in {"user", "assistant", "tool"}
        or payload["kind"] not in {"message", "test_result", "command_result"}
        or not 1 <= len(payload["text"]) <= 20_000
    ):
        return "invalid_request"
    sequence_no = payload.get("sequence_no")
    if isinstance(sequence_no, bool) or not isinstance(sequence_no, int) or sequence_no < 1:
        return "invalid_request"
    observed_at = _canonical_utc_timestamp(payload["observed_at"])
    if observed_at is None:
        return "invalid_timestamp"
    return ObserveRequest(
        project_id=payload["project_id"],
        session_id=payload["session_id"],
        event_id=payload["event_id"],
        sequence_no=sequence_no,
        actor=payload["actor"],
        kind=payload["kind"],
        observed_at=observed_at,
        text=payload["text"],
    )


def _canonical_utc_timestamp(value: str) -> str | None:
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    canonical = parsed.astimezone(timezone.utc).isoformat()
    return canonical.replace("+00:00", "Z")


def _compile_trace_summary(trace: dict[str, Any]) -> dict[str, Any]:
    return {
        "memory_snapshot_seq": trace["memory_snapshot_seq"],
        "active_candidate_count": trace["active_candidate_count"],
        "embedding_top_n": trace["embedding_top_n"],
        "rerank_input_count": trace["rerank_input_count"],
        "selected_count": trace["selected_count"],
        "omitted_count": trace["omitted_count"],
        "provider_mode": trace["provider_mode"],
    }


def _serialize_observe_response(
    request: ObserveRequest,
    response: Any,
    decider: Any,
) -> DemoResponse:
    event = {
        "project_id": request.project_id,
        "session_id": request.session_id,
        "event_id": request.event_id,
        "sequence_no": request.sequence_no,
        "project_event_seq": response.project_event_seq,
    }
    if response.status_code == 200:
        return _json_response(
            200,
            {
                "status_code": 200,
                "state": "completed",
                "replayed": response.replayed,
                "event": event,
                "final_result": response.final_result,
                "trace": {
                    "run_id": _observe_run_id(response),
                    "attempt_no": response.attempt_no or 1,
                    "provider_mode": response.provider_mode or "fake",
                    "repaired": response.repaired,
                    "request_id_present": response.request_id_present,
                },
            },
        )
    if response.status_code == 202:
        return _json_response(202, {"status_code": 202, "state": "pending", "event": event})
    if response.status_code == 503:
        return _json_response(
            503,
            {
                "status_code": 503,
                "error": response.error or "provider_network_error",
                "retryable": True,
                "run_id": _observe_run_id(response),
            },
        )
    return _observe_error_response(response.status_code, response.error or "invalid_request")


def _observe_run_id(response: Any) -> str:
    if isinstance(response.run_id, str) and response.run_id.startswith("run_"):
        return response.run_id
    event_id = response.event_internal_id or "unknown"
    attempt_no = response.attempt_no or 1
    return f"run_{event_id.removeprefix('evt_')}_{attempt_no}"


def _observe_error_response(status_code: int, error: str) -> DemoResponse:
    return _json_response(status_code, {"status_code": status_code, "error": error})


def _runtime_db_path() -> tuple[Path, str]:
    configured = os.environ.get("RECALLPACK_SQLITE_PATH")
    if configured:
        return Path(configured), "env"
    return (
        Path(tempfile.gettempdir())
        / f"recallpack-demo-{os.getpid()}-{_RUNTIME_NONCE}.sqlite3",
        "tempdir",
    )


def _runtime_artifact_root() -> Path:
    configured = os.environ.get("RECALLPACK_ARTIFACT_ROOT")
    if configured:
        return Path(configured)
    return (
        Path(tempfile.gettempdir())
        / f"recallpack-artifacts-{os.getpid()}-{_RUNTIME_NONCE}"
    )


def _compile_error_response(status_code: int, error: str) -> DemoResponse:
    payload: dict[str, Any] = {"status_code": status_code, "error": error}
    if status_code == 503:
        payload["artifacts_published"] = False
    return _json_response(status_code, payload)


def _ensure_demo_fixture_seeded(
    store: SqliteEventStore,
    fixture: Any,
    composition: RuntimeComposition = _STARTUP_COMPOSITION,
) -> bool:
    missing_fixture_event = any(
        not store.has_event(event.project_id, event.session_id, event.event_id)
        for event in fixture.events
    )
    if not missing_fixture_event:
        return False
    runtime = composition.create_observe_runtime(store=store, decider=_memory_decider())
    for event in fixture.events:
        runtime.observe(event, now=100 + event.sequence_no)
    return True


def _memory_decider() -> ProviderMemoryDecider:
    return ProviderMemoryDecider(FakeRuleBasedMemoryDecisionProvider())


def _demo_payload(root: Path) -> dict[str, Any]:
    live_trace_path = root / "docs" / "submission" / "live-qwen-trace.json"
    live_e2e_trace_path = root / "docs" / "submission" / "live-qwen-e2e-trace.json"
    fresh_m98_trace_path = root / "docs" / "submission" / "live-qwen-m98-rerun-trace.json"
    projectodyssey_trace_path = (
        root / "docs" / "submission" / "projectodyssey-live-qwen-e2e-trace.json"
    )
    return build_demo_payload(
        root / "fixtures" / "project-a",
        root / "fixtures" / "micro-suite",
        live_qwen_trace_path=live_trace_path if live_trace_path.is_file() else None,
        live_qwen_e2e_trace_path=(
            live_e2e_trace_path if live_e2e_trace_path.is_file() else None
        ),
        fresh_m98_live_rerun_trace_path=(
            fresh_m98_trace_path if fresh_m98_trace_path.is_file() else None
        ),
        projectodyssey_live_qwen_e2e_trace_path=(
            projectodyssey_trace_path if projectodyssey_trace_path.is_file() else None
        ),
        secondary_fixture_roots=discover_secondary_hero_fixture_roots(root),
    )


def _health_payload(root: Path) -> dict[str, Any]:
    payload = _demo_payload(root)
    story = payload["hero_story"]
    qwen = payload["qwen_load_bearing"]
    generalization = payload["evaluate"]["generalization_fixtures"]
    qwen_roles = sorted(
        {trace["provider_role"] for trace in qwen.get("provider_traces", [])}
    )
    return {
        "status": "ok",
        "project": "RecallPack",
        "track": "MemoryAgent",
        "credential_required_for_local_demo": False,
        "qwen": {
            "live_status": qwen["live_status"],
            "live_qwen_e2e_status": qwen.get("live_qwen_e2e_status", "not_claimed"),
            "stored_live_qwen_e2e_status": qwen.get(
                "stored_live_qwen_e2e_status",
                qwen.get("live_qwen_e2e_status", "not_claimed"),
            ),
            "fresh_m98_live_rerun_status": qwen.get(
                "fresh_m98_live_rerun_status",
                "gated_not_run",
            ),
            "projectodyssey_live_e2e_status": qwen.get(
                "projectodyssey_live_e2e_status",
                "not_claimed",
            ),
            "provider_roles": qwen_roles,
            "evidence_mode": (
                "stored sanitized one-run trace; local demo makes no live Qwen calls"
            ),
        },
        "proof": {
            "fixture_count": generalization["fixture_count"],
            "baseline_downstream_tests": _test_ratio(story["baseline"]["test_summary"]),
            "recallpack_downstream_tests": _test_ratio(story["recallpack"]["test_summary"]),
            "retrieval_path": story["retrieval_path"],
            "local_patch_generation_mode": "deterministic_context_keyed_patch_provider",
            "local_baseline_retrieval_mode": "keyword_scored_fake_embedding_rerank",
        },
        "runtime": {
            "deterministic_runtime": True,
            "local_only_default": True,
        },
    }


def _static_response(root: Path, path: str) -> DemoResponse:
    web_root = (root / "web").resolve()
    route = urlparse(path).path
    target = web_root / ("index.html" if route == "/" else route.lstrip("/"))
    try:
        resolved = target.resolve()
        resolved.relative_to(web_root)
    except ValueError:
        return _json_response(404, {"error": "not_found"})
    if not resolved.is_file():
        return _json_response(404, {"error": "not_found"})
    content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    return DemoResponse(
        status_code=200,
        headers={"content-type": content_type},
        body=resolved.read_bytes(),
    )


def _json_response(status_code: int, payload: dict[str, Any]) -> DemoResponse:
    return DemoResponse(
        status_code=status_code,
        headers={"content-type": "application/json; charset=utf-8"},
        body=json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"),
    )


def _test_ratio(summary: dict[str, int]) -> str:
    return f"{summary['passed']}/{summary['total']}"


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


if __name__ == "__main__":
    main()
