window.RECALLPACK_DEMO_DATA = {
  "deployment_proof": {
    "approval_required": true,
    "non_actions": [
      "no Qwen credentials are required by the deployed demo",
      "no live Qwen calls are made by the Docker runtime",
      "no Docker image was pushed",
      "no hackathon submission is performed by this deployment proof"
    ],
    "public_deployment": {
      "container": "recallpack-cloud",
      "image": "recallpack-demo:cloud",
      "judge_smoke_status": "passed",
      "platform": "Alibaba Cloud ECS",
      "port_mapping": "0.0.0.0:80->8789/tcp",
      "redeployed_at": "2026-07-04",
      "region": "cn-shanghai",
      "runtime": "ThreadingHTTPServer",
      "source_bundle": "latest sanitized bundle",
      "status": "approved_public_ecs_passed",
      "url": "http://101.133.224.223/"
    },
    "runtime_limits": {
      "application_workers": 1,
      "deployment_replicas": 1
    },
    "target": "Alibaba Cloud ECS + Docker + SQLite"
  },
  "evaluate": {
    "generalization_fixtures": {
      "credibility_note": "eight local fixtures cover retry, config, cache, serializer, pagination, realistic API-client auth migration, source-backed AI provider auth-header mode, and a source-backed ProjectOdyssey JIT scenario; project-h uses an unrigged keyword provider baseline with no fixture-authored baseline embedding terms or downrank phrases. This is stronger local evidence, not a broad benchmark.",
      "fixture_count": 8,
      "fixtures": [
        {
          "baseline_causal_reason": "stale retry policy selected: three fixed-delay attempts fail current retry fixture tests",
          "baseline_downstream_tests": "1/3",
          "baseline_rejection_code": null,
          "baseline_selected_sources": [
            "session-a:turn-008",
            "session-a:turn-001"
          ],
          "component": "retry",
          "fixture_structure": "single_session_linear_turn_ids",
          "goal": "Update the retry helper to follow the project's current retry policy.",
          "project_id": "project-a",
          "recallpack_causal_reason": "active retry policy selected: five attempts with exponential backoff and no dependency change",
          "recallpack_downstream_tests": "3/3",
          "recallpack_rejection_code": null,
          "recallpack_selected_sources": [
            "session-a:turn-005",
            "session-a:turn-003"
          ]
        },
        {
          "baseline_causal_reason": "stale config policy selected: return None fails current config fixture tests",
          "baseline_downstream_tests": "1/3",
          "baseline_rejection_code": null,
          "baseline_selected_sources": [
            "session-b:turn-001",
            "session-b:turn-002"
          ],
          "component": "config",
          "fixture_structure": "single_session_linear_turn_ids",
          "goal": "Update the config loader to follow the current missing-key policy.",
          "project_id": "project-b",
          "recallpack_causal_reason": "active config policy selected: raise ConfigError with the missing key name",
          "recallpack_downstream_tests": "3/3",
          "recallpack_rejection_code": null,
          "recallpack_selected_sources": [
            "session-b:turn-005",
            "session-b:turn-003"
          ]
        },
        {
          "baseline_causal_reason": "patch rejected by downstream path validator: empty_patch",
          "baseline_downstream_tests": "0/3",
          "baseline_rejection_code": "empty_patch",
          "baseline_selected_sources": [
            "session-c:turn-001",
            "session-c:turn-002"
          ],
          "component": "cache",
          "fixture_structure": "single_session_linear_turn_ids",
          "goal": "Update the cache policy to the current tenant-aware key and TTL.",
          "project_id": "project-c",
          "recallpack_causal_reason": "active cache policy selected: tenant-aware key with 60 second TTL",
          "recallpack_downstream_tests": "3/3",
          "recallpack_rejection_code": null,
          "recallpack_selected_sources": [
            "session-c:turn-005",
            "session-c:turn-003"
          ]
        },
        {
          "baseline_causal_reason": "patch rejected by downstream path validator: empty_patch",
          "baseline_downstream_tests": "0/3",
          "baseline_rejection_code": "empty_patch",
          "baseline_selected_sources": [
            "session-d:turn-008",
            "session-d:turn-001"
          ],
          "component": "serializer",
          "fixture_structure": "single_session_linear_turn_ids",
          "goal": "Update the audit serializer to the current redaction policy.",
          "project_id": "project-d",
          "recallpack_causal_reason": "active serializer policy selected: redact email values",
          "recallpack_downstream_tests": "3/3",
          "recallpack_rejection_code": null,
          "recallpack_selected_sources": [
            "session-d:turn-005",
            "session-d:turn-003"
          ]
        },
        {
          "baseline_causal_reason": "patch rejected by downstream path validator: empty_patch",
          "baseline_downstream_tests": "0/3",
          "baseline_rejection_code": "empty_patch",
          "baseline_selected_sources": [
            "session-e-alpha:note-002",
            "session-e-beta:pref-003"
          ],
          "component": "pagination",
          "fixture_structure": "non_isomorphic_multi_session_sparse_event_ids",
          "goal": "Update the pagination helper to the current cursor limit policy.",
          "project_id": "project-e",
          "recallpack_causal_reason": "active pagination policy selected: cursor tokens with limit clamped to 100",
          "recallpack_downstream_tests": "3/3",
          "recallpack_rejection_code": null,
          "recallpack_selected_sources": [
            "session-e-gamma:decision-001",
            "session-e-beta:pref-002"
          ]
        },
        {
          "baseline_causal_reason": "stale API client policy selected: Authorization header and timeout=5 fail current fixture tests",
          "baseline_downstream_tests": "1/3",
          "baseline_rejection_code": null,
          "baseline_selected_sources": [
            "session-f-setup:turn-002",
            "session-f-setup:turn-004"
          ],
          "component": "api_client",
          "fixture_structure": "realistic_repo_style_multi_session_with_noise",
          "goal": "Update the API client to the current authentication and timeout policy.",
          "project_id": "project-f-realistic",
          "recallpack_causal_reason": "active API client policy selected: X-Api-Key header with timeout=10",
          "recallpack_downstream_tests": "3/3",
          "recallpack_rejection_code": null,
          "recallpack_selected_sources": [
            "session-f-fix:turn-006",
            "session-f-setup:turn-004"
          ]
        },
        {
          "baseline_causal_reason": "stale provider auth policy selected: forwarding both Authorization and X-Api-Key fails current fixture tests",
          "baseline_downstream_tests": "1/3",
          "baseline_rejection_code": null,
          "baseline_selected_sources": [
            "session-g-alpha:turn-002",
            "session-g-alpha:turn-001"
          ],
          "component": "provider_auth",
          "fixture_structure": "source_backed_ai_provider_auth_header_mode",
          "goal": "Update the provider auth helper to the current upstream header-mode policy.",
          "project_id": "project-g-auth-mode",
          "recallpack_causal_reason": "active provider auth policy selected: standard mode strips Authorization and OAuth mode keeps Bearer",
          "recallpack_downstream_tests": "3/3",
          "recallpack_rejection_code": null,
          "recallpack_selected_sources": [
            "session-g-alpha:turn-004",
            "session-g-fix:turn-006"
          ]
        },
        {
          "baseline_causal_reason": "stale CI JIT policy selected: retry and nonblocking workarounds fail current fixture tests",
          "baseline_downstream_tests": "1/3",
          "baseline_rejection_code": null,
          "baseline_selected_sources": [
            "session-h-current:turn-004",
            "session-h-history:turn-002"
          ],
          "component": "ci_policy",
          "fixture_structure": "source_backed_projectodyssey_jit_unrigged_retrieval",
          "goal": "Fix the flaky Mojo JIT CI crash by updating retry handling.",
          "project_id": "project-h-projectodyssey-jit",
          "recallpack_causal_reason": "active CI JIT policy selected: fail fast and fix forward with a minimal reproducer",
          "recallpack_downstream_tests": "3/3",
          "recallpack_rejection_code": null,
          "recallpack_selected_sources": [
            "session-h-current:turn-006",
            "session-h-history:turn-004"
          ]
        }
      ],
      "status": "curated_lifecycle_regression_fixtures"
    },
    "hidden_tests": [
      "test_uses_current_retry_count",
      "test_uses_current_backoff_policy",
      "test_does_not_modify_dependencies"
    ],
    "micro_suite": {
      "case_count": 32,
      "confusion_matrix": {
        "duplicate": {
          "duplicate": 4,
          "no_op": 0,
          "write_independent": 0,
          "write_superseding": 0
        },
        "no_op": {
          "duplicate": 0,
          "no_op": 8,
          "write_independent": 0,
          "write_superseding": 0
        },
        "write_independent": {
          "duplicate": 0,
          "no_op": 0,
          "write_independent": 10,
          "write_superseding": 0
        },
        "write_superseding": {
          "duplicate": 0,
          "no_op": 0,
          "write_independent": 0,
          "write_superseding": 10
        }
      },
      "edge_counts": {
        "correct": 10,
        "gold": 10,
        "predicted": 10
      },
      "evidence_mode": "behavior_contract_fixture_suite",
      "metrics": {
        "edge_f1": 1.0,
        "edge_precision": 1.0,
        "edge_recall": 1.0,
        "memory_segment_tokens": 384,
        "memory_type_accuracy": 1.0,
        "required_memory_recall_at_512": 1.0,
        "should_create_memory_f1": 1.0,
        "should_create_memory_precision": 1.0,
        "should_create_memory_recall": 1.0,
        "stale_selected_items": 0
      },
      "positioning": "RecallPack micro-suite is a hackathon evidence suite, not a broad benchmark.",
      "prediction_evidence": {
        "case_count": 32,
        "decider_override_count": 0,
        "deprecated_prediction_field_case_count": 32,
        "prediction_source": "behavioral_runtime",
        "seed_event_count": 4,
        "used_fixture_predictions": false
      },
      "raw_counts": {
        "fn": 0,
        "fp": 0,
        "tn": 12,
        "tp": 20
      },
      "sections": [
        "raw_counts",
        "confusion_matrix",
        "edge_counts",
        "rates"
      ],
      "truthfulness_note": "The micro-suite is a behavior contract fixture suite: fixture-authored cases are replayed through the local runtime; it is not a broad benchmark."
    }
  },
  "evidence_boundary": {
    "do_not_claim": [
      "broad coding benchmark improvement",
      "universal retrieval superiority",
      "guaranteed live Qwen downstream success",
      "replacement for agent reasoning"
    ],
    "judge_note": "Local demo uses deterministic fake providers and a deterministic context-keyed patch provider; local demo makes no live Qwen calls. Stored live traces support lifecycle filtering, not a measured live baseline failure rate.",
    "live_qwen_evidence_mode": "stored_sanitized_one_run_trace",
    "local_baseline_retrieval_mode": "keyword_scored_fake_embedding_rerank",
    "local_patch_generation_mode": "deterministic_context_keyed_patch_provider",
    "micro_suite_mode": "behavior_contract_fixture_suite",
    "sections": [
      {
        "id": "live_qwen",
        "items": [
          "provider-path integration evidence: lifecycle filtering held in stored live RecallPack runs",
          "live raw-history embedding+rerank selected the active retry decision in stored baseline runs",
          "downstream live delta is one pass and one failed rerun, not a headline metric"
        ],
        "label": "Live Qwen"
      },
      {
        "id": "local_demo",
        "items": [
          "credential-free deterministic replay",
          "authored local 1/3 vs 3/3 failure-class illustration",
          "no live Qwen calls are made by the public demo runtime"
        ],
        "label": "Local Demo"
      },
      {
        "id": "behavior_contract",
        "items": [
          "eight curated lifecycle regression fixtures",
          "tests stale-memory handling behaviors, not a broad benchmark",
          "raw full history is reference-only and not budget-comparable"
        ],
        "label": "Behavior Contract"
      }
    ],
    "structural_claim": "RecallPack stores supersession at write time, when old and new decisions are both visible, so /compile can structurally exclude memory the project already reversed.",
    "summary": "Memory lifecycle proof first; Qwen evidence is provider-path integration evidence, not broad live downstream validation.",
    "title": "Evidence Boundary"
  },
  "handoff_replay": {
    "claims_live_qwen_e2e": false,
    "default_step_id": "stale_context",
    "evidence_mode": "existing downstream temp-repo patch and fixture-test execution",
    "local_patch_generation_mode": "deterministic_context_keyed_patch_provider",
    "mode_label": "Deterministic scripted replay",
    "play_label": "Replay handoff",
    "status": "local_fixture_evidence",
    "steps": [
      {
        "body": "The raw-history fake-embedding top-N baseline pulls the old three-attempt retry instruction into the handoff.",
        "evidence": "keyword-scored fake-embedding + rerank raw event context",
        "headline": "Baseline retrieves a superseded retry decision",
        "hidden_tests": "1/3",
        "id": "stale_context",
        "label": "Stale context selected",
        "memory_status": "superseded raw session memory selected",
        "patch_signal": "context contains stale retry policy",
        "result": "stale_context_selected",
        "selected_sources": [
          "session-a:turn-008",
          "session-a:turn-001"
        ],
        "variant_id": "embedding_top_k_rag"
      },
      {
        "body": "stale retry policy selected: three fixed-delay attempts fail current retry fixture tests",
        "evidence": "patch applied in temp repo; fixture tests pass 1/3",
        "headline": "Fresh agent writes the old retry behavior",
        "hidden_tests": "1/3",
        "id": "wrong_patch",
        "label": "Wrong retry patch",
        "memory_status": "superseded memory caused stale action",
        "patch_signal": "max_attempts=3 fixed-delay retry patch",
        "result": "wrong_retry_patch",
        "selected_sources": [
          "session-a:turn-008",
          "session-a:turn-001"
        ],
        "variant_id": "embedding_top_k_rag"
      },
      {
        "body": "The pack keeps the active retry decision and dependency preference under the fixed 512-token budget.",
        "evidence": "embedding top-N -> qwen3-rerank -> budget selector",
        "headline": "RecallPack filters stale memory before compile",
        "hidden_tests": "3/3",
        "id": "active_memory_pack",
        "label": "Active memory pack",
        "memory_status": "active lifecycle memories selected",
        "patch_signal": "active decision plus dependency preference",
        "result": "active_memory_pack_selected",
        "selected_sources": [
          "session-a:turn-005",
          "session-a:turn-003"
        ],
        "variant_id": "recallpack"
      },
      {
        "body": "active retry policy selected: five attempts with exponential backoff and no dependency change",
        "evidence": "patch applied in temp repo; fixture tests pass 3/3",
        "headline": "Fresh agent writes current retry behavior",
        "hidden_tests": "3/3",
        "id": "passing_patch",
        "label": "Passing retry patch",
        "memory_status": "active memory caused current action",
        "patch_signal": "max_attempts=5 exponential-backoff retry patch",
        "result": "correct_retry_patch",
        "selected_sources": [
          "session-a:turn-005",
          "session-a:turn-003"
        ],
        "variant_id": "recallpack"
      }
    ],
    "structural_claim": "This is an authored deterministic replay of a stale-handoff failure class. Stored live Qwen runs support the lifecycle filter: superseded memory was excluded before active memory was packed.",
    "task": "Update the retry helper to the current project policy.",
    "title": "Deterministic Stale-Memory Failure Replay",
    "truthfulness_note": "This local replay uses a deterministic context-keyed patch provider, not live Qwen inference."
  },
  "handoff_simulator": {
    "baseline": {
      "causal_reason": "stale retry policy selected: three fixed-delay attempts fail current retry fixture tests",
      "context_mode": "computed_embedding_top_k_raw_events",
      "hidden_tests": "1/3",
      "label": "Baseline stale handoff",
      "patch_signal": "max_attempts=3 fixed-delay retry patch",
      "selected_sources": [
        "session-a:turn-008",
        "session-a:turn-001"
      ]
    },
    "flow": [
      {
        "evidence": "new session has no implicit prior context",
        "id": "incoming_task",
        "label": "Fresh agent receives task"
      },
      {
        "evidence": "keyword-scored fake-embedding + rerank includes superseded retry memory",
        "id": "raw_history_baseline",
        "label": "Baseline recalls raw history"
      },
      {
        "evidence": "superseded memory is filtered before rerank and budget selection",
        "id": "recallpack_compile",
        "label": "RecallPack compiles active memory"
      },
      {
        "evidence": "same temp repo, same fixture tests, different handoff context",
        "id": "downstream_hidden_tests",
        "label": "Both patches run fixture tests"
      }
    ],
    "qwen_boundary": {
      "first_screen_lines": [
        "Standalone Qwen API smoke: passed",
        "Stored live provider-path E2E: one pass; fresh rerun failed",
        "ProjectOdyssey live E2E: passed",
        "Lifecycle filtering: held in stored live runs"
      ],
      "fresh_m98_live_rerun_status": "live_e2e_failed",
      "live_observe_compile_e2e_status": "live_e2e_passed",
      "live_status": "live_contract_passed",
      "model_work": [
        "memory extraction, type classification, and supersession judgment",
        "candidate memory retrieval with text-embedding-v4",
        "precision reranking with qwen3-rerank"
      ],
      "runtime_work": [
        "event ordering and lease fencing",
        "schema validation and failure handling",
        "active/superseded lifecycle filtering",
        "512-token budget selection",
        "PACK.md and recallpack.json assembly"
      ],
      "standalone_contract_status": "live_contract_passed",
      "stored_live_qwen_e2e_status": "live_e2e_passed"
    },
    "recallpack": {
      "causal_reason": "active retry policy selected: five attempts with exponential backoff and no dependency change",
      "context_mode": "active_memory_lifecycle_pack",
      "hidden_tests": "3/3",
      "label": "RecallPack active handoff",
      "patch_signal": "max_attempts=5 exponential-backoff retry patch",
      "selected_sources": [
        "session-a:turn-005",
        "session-a:turn-003"
      ]
    },
    "task": "Update the retry helper to the current project policy.",
    "title": "First-Run Handoff Simulator",
    "why_it_wins": [
      "local replay baseline retrieves stale raw history and writes the old retry policy",
      "RecallPack supersedes stale memory before compile",
      "RecallPack keeps the active retry decision plus dependency preference inside the 512-token pack",
      "both patches are executed in a temp repo against the same fixture tests"
    ]
  },
  "hero_story": {
    "baseline": {
      "causal_reason": "stale retry policy selected: three fixed-delay attempts fail current retry fixture tests",
      "label": "Embedding top-N + rerank stale baseline",
      "patch_signal": "max_attempts=3 fixed-delay retry patch",
      "test_summary": {
        "failed": 2,
        "passed": 1,
        "total": 3
      }
    },
    "failure_summary": "The local replay shows how budgeted retrieval can carry a superseded decision into a handoff. RecallPack filters superseded memory before rerank and budget selection.",
    "headline": "RecallPack makes stale-decision exclusion structural",
    "live_qwen_run": true,
    "live_qwen_status": "live_contract_passed",
    "memory_lifecycle_summary": {
      "active": [
        "mem_retry_current",
        "mem_dependency_policy"
      ],
      "superseded": [
        "mem_retry_old"
      ]
    },
    "patch_generation": {
      "baseline_model_name": "qwen3.7-plus-2026-05-26",
      "input_fields": [
        "goal",
        "selected_context",
        "allowed_edit_paths",
        "source_files"
      ],
      "live_mode": "stored_qwen_e2e_trace_only",
      "local_mode": "deterministic_context_keyed_patch_provider",
      "provider_role": "patch_generation",
      "recallpack_model_name": "qwen3.7-plus-2026-05-26",
      "request_purpose": "generate_patch_from_goal_and_selected_context",
      "same_provider_contract": true,
      "truthfulness_note": "Local downstream proof uses a local deterministic context-keyed patch provider; live Qwen patch generation is evidenced only by the stored sanitized E2E trace.",
      "used_gold_patch_variants": false
    },
    "recallpack": {
      "causal_reason": "active retry policy selected: five attempts with exponential backoff and no dependency change",
      "label": "RecallPack active-memory handoff",
      "patch_signal": "max_attempts=5 exponential-backoff retry patch",
      "test_summary": {
        "failed": 0,
        "passed": 3,
        "total": 3
      }
    },
    "retrieval_path": [
      "embedding top-N",
      "qwen3-rerank",
      "512-token budget selector"
    ]
  },
  "judge_first_screen": {
    "comparison": [
      {
        "downstream_tests": "3/3",
        "fairness_note": "all 12 events; useful as coverage reference, not a budget baseline",
        "id": "raw_full_history",
        "label": "Raw full history",
        "role": "reference_not_budget_comparable",
        "selection_source": "raw_full_history_unfiltered"
      },
      {
        "downstream_tests": "1/3",
        "fairness_note": "computed from raw event text with fake embeddings/rerank; not source-picked from gold selected-source IDs, but local scoring terms are fixture-authored",
        "id": "embedding_top_k_rag",
        "label": "Keyword fake-embedding + rerank RAG",
        "role": "computed_budget_baseline",
        "selection_source": "computed_embedding_top_k_raw_events",
        "source_recall_score": "0/3"
      },
      {
        "downstream_tests": "3/3",
        "fairness_note": "uses active lifecycle state, rerank, and fixed budget selection",
        "id": "recallpack",
        "label": "RecallPack",
        "role": "stale_aware_memory_lifecycle",
        "selection_source": "active_memory_compile"
      }
    ],
    "downstream_proof": "Both baseline and RecallPack patches are generated by the same local deterministic context-keyed patch provider from goal plus selected context, then run in temp repo fixture tests against fixture repo_snapshot. The stored live Qwen E2E trace separately shows one approved model-in-the-loop patch generation run.",
    "positioning": "MemoryAgent stale-aware lifecycle proof for coding-agent handoffs",
    "qwen_load_bearing": {
      "deterministic_runtime_work": [
        "event ordering and lease fencing",
        "schema validation and failure handling",
        "active/superseded lifecycle filtering",
        "512-token budget selection",
        "PACK.md and recallpack.json assembly"
      ],
      "fresh_m98_live_rerun_status": "live_e2e_failed",
      "live_qwen_e2e_status": "live_e2e_passed",
      "live_status": "live_contract_passed",
      "local_mode": "local tests use fake providers or the checked-in sanitized live trace; no credentials required",
      "model_work": [
        "memory extraction, type classification, and supersession judgment",
        "candidate memory retrieval with text-embedding-v4",
        "precision reranking with qwen3-rerank"
      ],
      "standalone_contract_status": "live_contract_passed",
      "stored_live_qwen_e2e_status": "live_e2e_passed"
    }
  },
  "learn": {
    "goal": "Update the retry helper to follow the project's current retry policy.",
    "memory_lifecycle": [
      {
        "id": "mem_retry_old",
        "source": "session-a:turn-001",
        "status": "superseded",
        "text": "Use three attempts with a fixed 100 ms delay."
      },
      {
        "id": "mem_retry_current",
        "source": "session-a:turn-005",
        "status": "active",
        "text": "Use five attempts with exponential backoff."
      },
      {
        "id": "mem_dependency_policy",
        "source": "session-a:turn-003",
        "status": "active",
        "text": "Keep retry behavior dependency-free."
      }
    ],
    "timeline": [
      {
        "actor": "user",
        "event_id": "turn-001",
        "sequence_no": 1,
        "text": "Use three attempts with a fixed 100 ms delay in the retry helper."
      },
      {
        "actor": "assistant",
        "event_id": "turn-002",
        "sequence_no": 2,
        "text": "I can inspect retry.py and the public retry tests."
      },
      {
        "actor": "user",
        "event_id": "turn-003",
        "sequence_no": 3,
        "text": "For this project, keep retry behavior dependency-free."
      },
      {
        "actor": "tool",
        "event_id": "turn-004",
        "sequence_no": 4,
        "text": "The last retry test failed because rate limits lasted longer than 300 ms."
      },
      {
        "actor": "user",
        "event_id": "turn-005",
        "sequence_no": 5,
        "text": "After the rate-limit failures, use five attempts with exponential backoff in the retry helper."
      },
      {
        "actor": "assistant",
        "event_id": "turn-006",
        "sequence_no": 6,
        "text": "I will keep the retry patch focused on the retry helper."
      },
      {
        "actor": "user",
        "event_id": "turn-007",
        "sequence_no": 7,
        "text": "That retry policy update replaces the earlier fixed-delay retry decision."
      },
      {
        "actor": "user",
        "event_id": "turn-008",
        "sequence_no": 8,
        "text": "Do not change pyproject.toml for this retry change."
      },
      {
        "actor": "assistant",
        "event_id": "turn-009",
        "sequence_no": 9,
        "text": "I can prepare a patch that edits only src/retry.py if no dependency change is needed."
      },
      {
        "actor": "user",
        "event_id": "turn-010",
        "sequence_no": 10,
        "text": "Auth uses bearer token validation; it is not part of the retry task."
      },
      {
        "actor": "user",
        "event_id": "turn-011",
        "sequence_no": 11,
        "text": "Cache cleanup can wait until after the retry work."
      },
      {
        "actor": "user",
        "event_id": "turn-012",
        "sequence_no": 12,
        "text": "Current handoff task: update the retry helper to the current project policy."
      }
    ]
  },
  "qwen_load_bearing": {
    "actual_qwen_token_usage": {
      "embedding_total_tokens": 20,
      "memory_decision_total_tokens": 301,
      "rerank_total_tokens": 29
    },
    "contract_summary": [
      "memory_decision live trace captured",
      "text-embedding-v4 live trace captured",
      "qwen3-rerank live trace captured"
    ],
    "deterministic_runtime_work": [
      "event ordering and lease fencing",
      "schema validation and failure handling",
      "active/superseded lifecycle filtering",
      "512-token budget selection",
      "PACK.md and recallpack.json assembly"
    ],
    "fresh_m98_live_rerun_source": "docs/submission/live-qwen-m98-rerun-trace.json",
    "fresh_m98_live_rerun_status": "live_e2e_failed",
    "fresh_m98_live_rerun_summary": "live_e2e_failed: baseline 2/3; RecallPack 2/3",
    "live_qwen_e2e_status": "live_e2e_passed",
    "live_qwen_run": true,
    "live_status": "live_contract_passed",
    "projectodyssey_live_e2e_source": "docs/submission/projectodyssey-live-qwen-e2e-trace.json",
    "projectodyssey_live_e2e_status": "live_e2e_passed",
    "projectodyssey_live_e2e_summary": "live_e2e_passed: baseline 1/3; RecallPack 3/3",
    "provider_traces": [
      {
        "deterministic_fallback_status": "live_qwen",
        "input_item_count": 2,
        "input_token_estimate": 165,
        "is_live": true,
        "model_name": "qwen-plus",
        "output_item_count": 1,
        "provider_role": "memory_decision",
        "request_id_present": true,
        "request_purpose": "extract_classify_and_judge_memory_lifecycle"
      },
      {
        "deterministic_fallback_status": "live_qwen",
        "input_item_count": 1,
        "input_token_estimate": 14,
        "is_live": true,
        "model_name": "text-embedding-v4",
        "output_item_count": 1,
        "provider_role": "embedding",
        "request_id_present": true,
        "request_purpose": "candidate_memory_retrieval_query"
      },
      {
        "deterministic_fallback_status": "live_qwen",
        "input_item_count": 1,
        "input_token_estimate": 11,
        "is_live": true,
        "model_name": "text-embedding-v4",
        "output_item_count": 1,
        "provider_role": "embedding",
        "request_id_present": true,
        "request_purpose": "candidate_memory_retrieval_document"
      },
      {
        "deterministic_fallback_status": "live_qwen",
        "input_item_count": 1,
        "input_token_estimate": 25,
        "is_live": true,
        "model_name": "qwen3-rerank",
        "output_item_count": 1,
        "provider_role": "rerank",
        "request_id_present": true,
        "request_purpose": "precision_rerank_active_memory_candidates"
      }
    ],
    "qwen_model_work": [
      "memory extraction, type classification, and supersession judgment",
      "candidate memory retrieval with text-embedding-v4",
      "precision reranking with qwen3-rerank"
    ],
    "standalone_contract_status": "live_contract_passed",
    "stored_live_qwen_e2e_status": "live_e2e_passed",
    "trace_explorer": {
      "display_title": "Stored Live Qwen Trace",
      "downstream_summary": "baseline 1/3; RecallPack 3/3",
      "excluded_sources_checked": [
        "session-a:turn-001"
      ],
      "observed_event_count": 12,
      "role_summary": [
        {
          "actual_tokens": 22297,
          "input_token_estimate": 11283,
          "live_trace_count": 12,
          "model_name": "qwen3.7-plus-2026-05-26",
          "output_item_count": 12,
          "provider_role": "memory_decision",
          "token_usage_key": "memory_decision_total_tokens",
          "trace_count": 12
        },
        {
          "actual_tokens": 108,
          "input_token_estimate": 117,
          "live_trace_count": 4,
          "model_name": "text-embedding-v4",
          "output_item_count": 4,
          "provider_role": "embedding",
          "token_usage_key": "embedding_total_tokens",
          "trace_count": 4
        },
        {
          "actual_tokens": 205,
          "input_token_estimate": 116,
          "live_trace_count": 1,
          "model_name": "qwen3-rerank",
          "output_item_count": 3,
          "provider_role": "rerank",
          "token_usage_key": "rerank_total_tokens",
          "trace_count": 1
        },
        {
          "actual_tokens": 1465,
          "input_token_estimate": 74,
          "live_trace_count": 2,
          "model_name": "qwen3.7-plus-2026-05-26",
          "output_item_count": 2,
          "provider_role": "patch_generation",
          "token_usage_key": "patch_generation_total_tokens",
          "trace_count": 2
        }
      ],
      "safety_boundary": {
        "local_demo_no_live_calls": true,
        "no_credentials": true,
        "no_raw_memory_text": true,
        "prompts_redacted": true,
        "provenance_verified": true,
        "sanitized_trace_only": true,
        "stored_trace_no_live_call": true
      },
      "selected_sources": [
        "session-a:turn-005",
        "session-a:turn-004",
        "session-a:turn-003"
      ],
      "source": "docs/submission/live-qwen-e2e-trace.json",
      "source_kind": "checked_in_sanitized_trace",
      "stages": [
        {
          "id": "observe_memory_decisions",
          "label": "Observe memory decisions",
          "model_work": "extract, classify, duplicate-check, and judge supersession",
          "provider_role": "memory_decision",
          "trace_count": 12
        },
        {
          "candidate_count": 3,
          "embedding_top_n_count": 3,
          "id": "compile_embedding_retrieval",
          "label": "Compile embedding retrieval",
          "model_work": "embed goal and active memory documents",
          "provider_role": "embedding",
          "trace_count": 4
        },
        {
          "id": "compile_rerank",
          "label": "Compile rerank",
          "model_work": "rerank embedding top-N candidates before budget selection",
          "provider_role": "rerank",
          "selected_count": 3,
          "trace_count": 1
        },
        {
          "id": "downstream_patch_generation",
          "label": "Downstream patch generation",
          "mode_note": "stored live E2E uses Qwen patch generation; local demo uses a deterministic context-keyed patch provider",
          "model_work": "stored live E2E trace records Qwen patch generation; local demo patch proof uses a deterministic context-keyed provider",
          "provider_role": "patch_generation",
          "same_provider_contract": true,
          "trace_count": 2,
          "used_gold_patch_variants": false
        }
      ],
      "status": "live_e2e_passed"
    }
  },
  "recall": {
    "goal": "Update the retry helper to follow the project's current retry policy.",
    "pack": {
      "budget_tokens": 512,
      "memories": [
        {
          "id": "mem_3704ea8f7e494ba9abb3b279b27a2917",
          "scope": "component:retry",
          "source_ref": "session-a:turn-005",
          "subject": "retry_policy",
          "text": "Use five attempts with exponential backoff.",
          "type": "decision"
        },
        {
          "id": "mem_5ba99a1f75594be08b0cf2fb0e0fa82f",
          "scope": "project",
          "source_ref": "session-a:turn-003",
          "subject": "dependency_policy",
          "text": "Do not add new dependencies.",
          "type": "preference"
        }
      ],
      "memory_segment_tokens": 123
    },
    "pipeline": [
      "observe ordered session events",
      "write durable memories",
      "supersede stale decisions",
      "embedding top-N retrieval",
      "rerank active candidates",
      "select a 512-token pack"
    ],
    "variants": [
      {
        "compile_trace": {
          "budget_comparable": false,
          "candidate_count": 12,
          "selected_count": 12,
          "selection_source": "raw_full_history_unfiltered"
        },
        "downstream": {
          "accepted": true,
          "causal_reason": "active retry policy selected: five attempts with exponential backoff and no dependency change",
          "execution_mode": "temp_repo_hidden_tests",
          "patch_diff": "--- a/src/retry.py\n+++ b/src/retry.py\n@@ -1,12 +1,13 @@\n import time\n \n \n-def retry(operation, max_attempts=3, delay_seconds=0.1):\n+def retry(operation, max_attempts=5, delay_seconds=0.1):\n     last_error = None\n-    for _ in range(max_attempts):\n+    for attempt in range(max_attempts):\n         try:\n             return operation()\n         except Exception as exc:\n             last_error = exc\n-            time.sleep(delay_seconds)\n+            if attempt < max_attempts - 1:\n+                time.sleep(delay_seconds * (2 ** attempt))\n     raise last_error\n",
          "patch_generation": {
            "deterministic_fallback_status": "fake_provider_deterministic",
            "generation_mode": "unspecified",
            "input_fields": [
              "goal",
              "selected_context",
              "allowed_edit_paths",
              "source_files"
            ],
            "input_item_count": 13,
            "input_token_estimate": 181,
            "is_live": false,
            "latency_ms": 0,
            "model_name": "qwen3.7-plus-2026-05-26",
            "output_item_count": 1,
            "output_paths": [
              "src/retry.py"
            ],
            "provider_name": "fake-qwen-patch-generator",
            "provider_role": "patch_generation",
            "request_id": "fake-patch-1",
            "request_id_present": true,
            "request_purpose": "generate_patch_from_goal_and_selected_context",
            "selected_context_source_refs": [
              "session-a:turn-001",
              "session-a:turn-002",
              "session-a:turn-003",
              "session-a:turn-004",
              "session-a:turn-005",
              "session-a:turn-006",
              "session-a:turn-007",
              "session-a:turn-008",
              "session-a:turn-009",
              "session-a:turn-010",
              "session-a:turn-011",
              "session-a:turn-012"
            ],
            "source_file_paths": [
              "src/retry.py",
              "pyproject.toml"
            ],
            "used_gold_patch_variants": false
          },
          "summary": {
            "failed": 0,
            "passed": 3
          },
          "tests": [
            {
              "detail": "attempts=5",
              "name": "test_uses_current_retry_count",
              "passed": true
            },
            {
              "detail": "sleeps=[0.1, 0.2, 0.4, 0.8]",
              "name": "test_uses_current_backoff_policy",
              "passed": true
            },
            {
              "detail": "dependencies=[]",
              "name": "test_does_not_modify_dependencies",
              "passed": true
            }
          ],
          "variant_id": "raw_full_history"
        },
        "id": "raw_full_history",
        "label": "Raw full history",
        "metrics": {
          "hidden_test_pass_count": 2,
          "memory_segment_tokens": 687,
          "required_memory_recall_at_budget": 1.0,
          "stale_leakage_rate": 0.08333333333333333
        },
        "selected_context": [
          {
            "actor": "user",
            "id": "session-a_turn-001",
            "kind": "message",
            "scope": "raw_history",
            "source_ref": "session-a:turn-001",
            "subject": "session_event",
            "text": "Use three attempts with a fixed 100 ms delay in the retry helper.",
            "type": "raw_event"
          },
          {
            "actor": "assistant",
            "id": "session-a_turn-002",
            "kind": "message",
            "scope": "raw_history",
            "source_ref": "session-a:turn-002",
            "subject": "session_event",
            "text": "I can inspect retry.py and the public retry tests.",
            "type": "raw_event"
          },
          {
            "actor": "user",
            "id": "session-a_turn-003",
            "kind": "message",
            "scope": "raw_history",
            "source_ref": "session-a:turn-003",
            "subject": "session_event",
            "text": "For this project, keep retry behavior dependency-free.",
            "type": "raw_event"
          },
          {
            "actor": "tool",
            "id": "session-a_turn-004",
            "kind": "test_result",
            "scope": "raw_history",
            "source_ref": "session-a:turn-004",
            "subject": "session_event",
            "text": "The last retry test failed because rate limits lasted longer than 300 ms.",
            "type": "raw_event"
          },
          {
            "actor": "user",
            "id": "session-a_turn-005",
            "kind": "message",
            "scope": "raw_history",
            "source_ref": "session-a:turn-005",
            "subject": "session_event",
            "text": "After the rate-limit failures, use five attempts with exponential backoff in the retry helper.",
            "type": "raw_event"
          },
          {
            "actor": "assistant",
            "id": "session-a_turn-006",
            "kind": "message",
            "scope": "raw_history",
            "source_ref": "session-a:turn-006",
            "subject": "session_event",
            "text": "I will keep the retry patch focused on the retry helper.",
            "type": "raw_event"
          },
          {
            "actor": "user",
            "id": "session-a_turn-007",
            "kind": "message",
            "scope": "raw_history",
            "source_ref": "session-a:turn-007",
            "subject": "session_event",
            "text": "That retry policy update replaces the earlier fixed-delay retry decision.",
            "type": "raw_event"
          },
          {
            "actor": "user",
            "id": "session-a_turn-008",
            "kind": "message",
            "scope": "raw_history",
            "source_ref": "session-a:turn-008",
            "subject": "session_event",
            "text": "Do not change pyproject.toml for this retry change.",
            "type": "raw_event"
          },
          {
            "actor": "assistant",
            "id": "session-a_turn-009",
            "kind": "message",
            "scope": "raw_history",
            "source_ref": "session-a:turn-009",
            "subject": "session_event",
            "text": "I can prepare a patch that edits only src/retry.py if no dependency change is needed.",
            "type": "raw_event"
          },
          {
            "actor": "user",
            "id": "session-a_turn-010",
            "kind": "message",
            "scope": "raw_history",
            "source_ref": "session-a:turn-010",
            "subject": "session_event",
            "text": "Auth uses bearer token validation; it is not part of the retry task.",
            "type": "raw_event"
          },
          {
            "actor": "user",
            "id": "session-a_turn-011",
            "kind": "message",
            "scope": "raw_history",
            "source_ref": "session-a:turn-011",
            "subject": "session_event",
            "text": "Cache cleanup can wait until after the retry work.",
            "type": "raw_event"
          },
          {
            "actor": "user",
            "id": "session-a_turn-012",
            "kind": "message",
            "scope": "raw_history",
            "source_ref": "session-a:turn-012",
            "subject": "session_event",
            "text": "Current handoff task: update the retry helper to the current project policy.",
            "type": "raw_event"
          }
        ]
      },
      {
        "compile_trace": {
          "candidate_count": 12,
          "embedding_top_k": 2,
          "embedding_top_n_count": 4,
          "provider_traces": [
            {
              "deterministic_fallback_status": "fake_provider_deterministic",
              "input_item_count": 1,
              "input_token_estimate": 18,
              "is_live": false,
              "latency_ms": 0,
              "model_name": "text-embedding-v4",
              "output_item_count": 1,
              "provider_role": "embedding",
              "request_id": "fake-embed_query-1",
              "request_id_present": true,
              "request_purpose": "candidate_memory_retrieval_query"
            },
            {
              "deterministic_fallback_status": "fake_provider_deterministic",
              "input_item_count": 1,
              "input_token_estimate": 35,
              "is_live": false,
              "latency_ms": 0,
              "model_name": "text-embedding-v4",
              "output_item_count": 1,
              "provider_role": "embedding",
              "request_id": "fake-embed_document-9",
              "request_id_present": true,
              "request_purpose": "candidate_memory_retrieval_document"
            },
            {
              "deterministic_fallback_status": "fake_provider_deterministic",
              "input_item_count": 1,
              "input_token_estimate": 39,
              "is_live": false,
              "latency_ms": 0,
              "model_name": "text-embedding-v4",
              "output_item_count": 1,
              "provider_role": "embedding",
              "request_id": "fake-embed_document-2",
              "request_id_present": true,
              "request_purpose": "candidate_memory_retrieval_document"
            },
            {
              "deterministic_fallback_status": "fake_provider_deterministic",
              "input_item_count": 1,
              "input_token_estimate": 39,
              "is_live": false,
              "latency_ms": 0,
              "model_name": "text-embedding-v4",
              "output_item_count": 1,
              "provider_role": "embedding",
              "request_id": "fake-embed_document-11",
              "request_id_present": true,
              "request_purpose": "candidate_memory_retrieval_document"
            },
            {
              "deterministic_fallback_status": "fake_provider_deterministic",
              "input_item_count": 1,
              "input_token_estimate": 35,
              "is_live": false,
              "latency_ms": 0,
              "model_name": "text-embedding-v4",
              "output_item_count": 1,
              "provider_role": "embedding",
              "request_id": "fake-embed_document-12",
              "request_id_present": true,
              "request_purpose": "candidate_memory_retrieval_document"
            },
            {
              "deterministic_fallback_status": "fake_provider_deterministic",
              "input_item_count": 1,
              "input_token_estimate": 36,
              "is_live": false,
              "latency_ms": 0,
              "model_name": "text-embedding-v4",
              "output_item_count": 1,
              "provider_role": "embedding",
              "request_id": "fake-embed_document-4",
              "request_id_present": true,
              "request_purpose": "candidate_memory_retrieval_document"
            },
            {
              "deterministic_fallback_status": "fake_provider_deterministic",
              "input_item_count": 1,
              "input_token_estimate": 46,
              "is_live": false,
              "latency_ms": 0,
              "model_name": "text-embedding-v4",
              "output_item_count": 1,
              "provider_role": "embedding",
              "request_id": "fake-embed_document-6",
              "request_id_present": true,
              "request_purpose": "candidate_memory_retrieval_document"
            },
            {
              "deterministic_fallback_status": "fake_provider_deterministic",
              "input_item_count": 1,
              "input_token_estimate": 36,
              "is_live": false,
              "latency_ms": 0,
              "model_name": "text-embedding-v4",
              "output_item_count": 1,
              "provider_role": "embedding",
              "request_id": "fake-embed_document-3",
              "request_id_present": true,
              "request_purpose": "candidate_memory_retrieval_document"
            },
            {
              "deterministic_fallback_status": "fake_provider_deterministic",
              "input_item_count": 1,
              "input_token_estimate": 42,
              "is_live": false,
              "latency_ms": 0,
              "model_name": "text-embedding-v4",
              "output_item_count": 1,
              "provider_role": "embedding",
              "request_id": "fake-embed_document-5",
              "request_id_present": true,
              "request_purpose": "candidate_memory_retrieval_document"
            },
            {
              "deterministic_fallback_status": "fake_provider_deterministic",
              "input_item_count": 1,
              "input_token_estimate": 38,
              "is_live": false,
              "latency_ms": 0,
              "model_name": "text-embedding-v4",
              "output_item_count": 1,
              "provider_role": "embedding",
              "request_id": "fake-embed_document-7",
              "request_id_present": true,
              "request_purpose": "candidate_memory_retrieval_document"
            },
            {
              "deterministic_fallback_status": "fake_provider_deterministic",
              "input_item_count": 1,
              "input_token_estimate": 41,
              "is_live": false,
              "latency_ms": 0,
              "model_name": "text-embedding-v4",
              "output_item_count": 1,
              "provider_role": "embedding",
              "request_id": "fake-embed_document-8",
              "request_id_present": true,
              "request_purpose": "candidate_memory_retrieval_document"
            },
            {
              "deterministic_fallback_status": "fake_provider_deterministic",
              "input_item_count": 1,
              "input_token_estimate": 45,
              "is_live": false,
              "latency_ms": 0,
              "model_name": "text-embedding-v4",
              "output_item_count": 1,
              "provider_role": "embedding",
              "request_id": "fake-embed_document-10",
              "request_id_present": true,
              "request_purpose": "candidate_memory_retrieval_document"
            },
            {
              "deterministic_fallback_status": "fake_provider_deterministic",
              "input_item_count": 1,
              "input_token_estimate": 41,
              "is_live": false,
              "latency_ms": 0,
              "model_name": "text-embedding-v4",
              "output_item_count": 1,
              "provider_role": "embedding",
              "request_id": "fake-embed_document-13",
              "request_id_present": true,
              "request_purpose": "candidate_memory_retrieval_document"
            },
            {
              "deterministic_fallback_status": "fake_provider_deterministic",
              "input_item_count": 4,
              "input_token_estimate": 165,
              "is_live": false,
              "latency_ms": 0,
              "model_name": "qwen3-rerank",
              "output_item_count": 4,
              "provider_role": "rerank",
              "request_id": "fake-rerank-1",
              "request_id_present": true,
              "request_purpose": "precision_rerank_active_memory_candidates"
            }
          ],
          "ranked_sources": [
            {
              "similarity": 0.948683,
              "source_ref": "session-a:turn-008"
            },
            {
              "similarity": 0.894427,
              "source_ref": "session-a:turn-001"
            },
            {
              "similarity": 0.894427,
              "source_ref": "session-a:turn-010"
            },
            {
              "similarity": 0.894427,
              "source_ref": "session-a:turn-011"
            },
            {
              "similarity": 0.868243,
              "source_ref": "session-a:turn-003"
            },
            {
              "similarity": 0.715542,
              "source_ref": "session-a:turn-005"
            },
            {
              "similarity": 0.0,
              "source_ref": "session-a:turn-002"
            },
            {
              "similarity": 0.0,
              "source_ref": "session-a:turn-004"
            },
            {
              "similarity": 0.0,
              "source_ref": "session-a:turn-006"
            },
            {
              "similarity": 0.0,
              "source_ref": "session-a:turn-007"
            },
            {
              "similarity": 0.0,
              "source_ref": "session-a:turn-009"
            },
            {
              "similarity": 0.0,
              "source_ref": "session-a:turn-012"
            }
          ],
          "rerank_input_count": 4,
          "reranked_sources": [
            {
              "rerank_position": 1,
              "source_ref": "session-a:turn-008"
            },
            {
              "rerank_position": 2,
              "source_ref": "session-a:turn-001"
            },
            {
              "rerank_position": 3,
              "source_ref": "session-a:turn-010"
            },
            {
              "rerank_position": 4,
              "source_ref": "session-a:turn-011"
            }
          ],
          "retrieval_mode": "embedding_top_n_rerank_raw_history",
          "selected_count": 2,
          "selection_source": "computed_embedding_top_k_raw_events"
        },
        "downstream": {
          "accepted": true,
          "causal_reason": "stale retry policy selected: three fixed-delay attempts fail current retry fixture tests",
          "execution_mode": "temp_repo_hidden_tests",
          "patch_diff": "--- a/src/retry.py\n+++ b/src/retry.py\n@@ -3,10 +3,11 @@\n \n def retry(operation, max_attempts=3, delay_seconds=0.1):\n     last_error = None\n-    for _ in range(max_attempts):\n+    for attempt in range(max_attempts):\n         try:\n             return operation()\n         except Exception as exc:\n             last_error = exc\n-            time.sleep(delay_seconds)\n+            if attempt < max_attempts - 1:\n+                time.sleep(delay_seconds)\n     raise last_error\n",
          "patch_generation": {
            "deterministic_fallback_status": "fake_provider_deterministic",
            "generation_mode": "unspecified",
            "input_fields": [
              "goal",
              "selected_context",
              "allowed_edit_paths",
              "source_files"
            ],
            "input_item_count": 3,
            "input_token_estimate": 68,
            "is_live": false,
            "latency_ms": 0,
            "model_name": "qwen3.7-plus-2026-05-26",
            "output_item_count": 1,
            "output_paths": [
              "src/retry.py"
            ],
            "provider_name": "fake-qwen-patch-generator",
            "provider_role": "patch_generation",
            "request_id": "fake-patch-1",
            "request_id_present": true,
            "request_purpose": "generate_patch_from_goal_and_selected_context",
            "selected_context_source_refs": [
              "session-a:turn-008",
              "session-a:turn-001"
            ],
            "source_file_paths": [
              "src/retry.py",
              "pyproject.toml"
            ],
            "used_gold_patch_variants": false
          },
          "summary": {
            "failed": 2,
            "passed": 1
          },
          "tests": [
            {
              "detail": "RuntimeError: transient failure; attempts=3",
              "name": "test_uses_current_retry_count",
              "passed": false
            },
            {
              "detail": "sleeps=[0.1, 0.1]",
              "name": "test_uses_current_backoff_policy",
              "passed": false
            },
            {
              "detail": "dependencies=[]",
              "name": "test_does_not_modify_dependencies",
              "passed": true
            }
          ],
          "variant_id": "embedding_top_k_rag"
        },
        "id": "embedding_top_k_rag",
        "label": "Embedding top-N + rerank RAG",
        "metrics": {
          "hidden_test_pass_count": 0,
          "memory_segment_tokens": 119,
          "required_memory_recall_at_budget": 0.0,
          "stale_leakage_rate": 0.5
        },
        "selected_context": [
          {
            "actor": "user",
            "id": "session-a_turn-008",
            "kind": "message",
            "scope": "raw_history",
            "source_ref": "session-a:turn-008",
            "subject": "session_event",
            "text": "Do not change pyproject.toml for this retry change.",
            "type": "raw_event"
          },
          {
            "actor": "user",
            "id": "session-a_turn-001",
            "kind": "message",
            "scope": "raw_history",
            "source_ref": "session-a:turn-001",
            "subject": "session_event",
            "text": "Use three attempts with a fixed 100 ms delay in the retry helper.",
            "type": "raw_event"
          }
        ]
      },
      {
        "compile_trace": {
          "active_candidate_count": 2,
          "artifact_provider_traces": [
            {
              "deterministic_fallback": true,
              "input_item_count": 1,
              "input_token_estimate": 18,
              "latency_ms": 0,
              "live": false,
              "model_name": "text-embedding-v4",
              "output_item_count": 1,
              "provider_family": "deterministic_fake",
              "request_id_present": true,
              "request_purpose": "candidate_memory_retrieval_query",
              "role": "embedding",
              "token_usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "reported_by_provider": false,
                "total_tokens": 0
              }
            },
            {
              "deterministic_fallback": true,
              "input_item_count": 2,
              "input_token_estimate": 68,
              "latency_ms": 0,
              "live": false,
              "model_name": "qwen3-rerank",
              "output_item_count": 2,
              "provider_family": "deterministic_fake",
              "request_id_present": true,
              "request_purpose": "precision_rerank_active_memory_candidates",
              "role": "rerank",
              "token_usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "reported_by_provider": false,
                "total_tokens": 0
              }
            }
          ],
          "candidate_count": 2,
          "candidate_scores": [
            {
              "candidate_index": 0,
              "embedding_cosine": 0.30316953129541624,
              "lifecycle_status": "active",
              "memory_id": "mem_3704ea8f7e494ba9abb3b279b27a2917",
              "rerank_score": 2.0,
              "scope": "component:retry",
              "source_project_event_seq": 5,
              "source_ref": "session-a:turn-005"
            },
            {
              "candidate_index": 1,
              "embedding_cosine": 0.1386750490563073,
              "lifecycle_status": "active",
              "memory_id": "mem_5ba99a1f75594be08b0cf2fb0e0fa82f",
              "rerank_score": 1.0,
              "scope": "project",
              "source_project_event_seq": 3,
              "source_ref": "session-a:turn-003"
            }
          ],
          "embedding_top_n": 20,
          "embedding_top_n_count": 2,
          "memory_snapshot_seq": 10,
          "omissions": [],
          "omitted_by_embedding_memory_ids": [],
          "omitted_count": 0,
          "omitted_memory_ids": [],
          "provider_mode": "fake",
          "provider_traces": [
            {
              "deterministic_fallback_status": "fake_provider_deterministic",
              "input_item_count": 1,
              "input_token_estimate": 18,
              "is_live": false,
              "latency_ms": 0,
              "model_name": "text-embedding-v4",
              "output_item_count": 1,
              "provider_role": "embedding",
              "request_id": "fake-keyword-embed_query-1",
              "request_id_present": true,
              "request_purpose": "candidate_memory_retrieval_query"
            },
            {
              "deterministic_fallback_status": "fake_provider_deterministic",
              "input_item_count": 2,
              "input_token_estimate": 68,
              "is_live": false,
              "latency_ms": 0,
              "model_name": "qwen3-rerank",
              "output_item_count": 2,
              "provider_role": "rerank",
              "request_id": "fake-rerank-1",
              "request_id_present": true,
              "request_purpose": "precision_rerank_active_memory_candidates"
            }
          ],
          "rerank_input_count": 2,
          "reranked_memory_ids": [
            "mem_3704ea8f7e494ba9abb3b279b27a2917",
            "mem_5ba99a1f75594be08b0cf2fb0e0fa82f"
          ],
          "retrieval_mode": "embedding_top_n",
          "retrieved_memory_ids": [
            "mem_3704ea8f7e494ba9abb3b279b27a2917",
            "mem_5ba99a1f75594be08b0cf2fb0e0fa82f"
          ],
          "selected_count": 2
        },
        "downstream": {
          "accepted": true,
          "causal_reason": "active retry policy selected: five attempts with exponential backoff and no dependency change",
          "execution_mode": "temp_repo_hidden_tests",
          "patch_diff": "--- a/src/retry.py\n+++ b/src/retry.py\n@@ -1,12 +1,13 @@\n import time\n \n \n-def retry(operation, max_attempts=3, delay_seconds=0.1):\n+def retry(operation, max_attempts=5, delay_seconds=0.1):\n     last_error = None\n-    for _ in range(max_attempts):\n+    for attempt in range(max_attempts):\n         try:\n             return operation()\n         except Exception as exc:\n             last_error = exc\n-            time.sleep(delay_seconds)\n+            if attempt < max_attempts - 1:\n+                time.sleep(delay_seconds * (2 ** attempt))\n     raise last_error\n",
          "patch_generation": {
            "deterministic_fallback_status": "fake_provider_deterministic",
            "generation_mode": "unspecified",
            "input_fields": [
              "goal",
              "selected_context",
              "allowed_edit_paths",
              "source_files"
            ],
            "input_item_count": 3,
            "input_token_estimate": 58,
            "is_live": false,
            "latency_ms": 0,
            "model_name": "qwen3.7-plus-2026-05-26",
            "output_item_count": 1,
            "output_paths": [
              "src/retry.py"
            ],
            "provider_name": "fake-qwen-patch-generator",
            "provider_role": "patch_generation",
            "request_id": "fake-patch-1",
            "request_id_present": true,
            "request_purpose": "generate_patch_from_goal_and_selected_context",
            "selected_context_source_refs": [
              "session-a:turn-005",
              "session-a:turn-003"
            ],
            "source_file_paths": [
              "src/retry.py",
              "pyproject.toml"
            ],
            "used_gold_patch_variants": false
          },
          "summary": {
            "failed": 0,
            "passed": 3
          },
          "tests": [
            {
              "detail": "attempts=5",
              "name": "test_uses_current_retry_count",
              "passed": true
            },
            {
              "detail": "sleeps=[0.1, 0.2, 0.4, 0.8]",
              "name": "test_uses_current_backoff_policy",
              "passed": true
            },
            {
              "detail": "dependencies=[]",
              "name": "test_does_not_modify_dependencies",
              "passed": true
            }
          ],
          "variant_id": "recallpack"
        },
        "id": "recallpack",
        "label": "RecallPack",
        "metrics": {
          "hidden_test_pass_count": 3,
          "memory_segment_tokens": 123,
          "required_memory_recall_at_budget": 1.0,
          "stale_leakage_rate": 0.0
        },
        "selected_context": [
          {
            "id": "mem_3704ea8f7e494ba9abb3b279b27a2917",
            "scope": "component:retry",
            "source_ref": "session-a:turn-005",
            "subject": "retry_policy",
            "text": "Use five attempts with exponential backoff.",
            "type": "decision"
          },
          {
            "id": "mem_5ba99a1f75594be08b0cf2fb0e0fa82f",
            "scope": "project",
            "source_ref": "session-a:turn-003",
            "subject": "dependency_policy",
            "text": "Do not add new dependencies.",
            "type": "preference"
          }
        ]
      }
    ]
  },
  "subtitle": "Stale-aware memory lifecycle for coding-agent handoffs",
  "title": "RecallPack",
  "views": [
    {
      "id": "learn",
      "label": "Learn"
    },
    {
      "id": "recall",
      "label": "Recall"
    },
    {
      "id": "evaluate",
      "label": "Evaluate"
    }
  ]
};
