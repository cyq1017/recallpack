const data = window.RECALLPACK_DEMO_DATA;
const app = document.querySelector("#app");
const tabbar = document.querySelector(".tabbar");
const validViewIds = new Set(data.views.map((view) => view.id));

let activeView = initialViewFromUrl();
let activeReplayStep = null;

function initialViewFromUrl() {
  const searchParams = new URLSearchParams(window.location.search);
  const view = searchParams.get("view");
  return validViewIds.has(view) ? view : "learn";
}

function setActiveView(viewId) {
  if (!validViewIds.has(viewId)) return;
  activeView = viewId;
  const url = new URL(window.location.href);
  url.searchParams.set("view", viewId);
  window.history.replaceState({}, "", url);
  render();
}

function setActiveReplayStep(stepId) {
  activeReplayStep = stepId;
  render();
}

function scrollToRequestedSection() {
  const targetId = window.location.hash.slice(1);
  if (!targetId) return;
  document.getElementById(targetId)?.scrollIntoView();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatMetric(value) {
  if (typeof value !== "number") return escapeHtml(value);
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(2);
}

function metric(label, value) {
  return `
    <div class="metric">
      <span class="metric-label">${escapeHtml(label)}</span>
      <span class="metric-value">${formatMetric(value)}</span>
    </div>
  `;
}

function renderTabs() {
  tabbar.innerHTML = data.views
    .map(
      (view) => `
        <button type="button" data-view="${escapeHtml(view.id)}"
          aria-selected="${view.id === activeView}">
          ${escapeHtml(view.label)}
        </button>
      `,
    )
    .join("");
  tabbar.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      setActiveView(button.dataset.view);
    });
  });
}

function renderLearn() {
  const timeline = data.learn.timeline
    .map(
      (event) => `
        <article class="event-row">
          <div>
            <div class="event-meta">#${event.sequence_no}</div>
            <div class="badge">${escapeHtml(event.actor)}</div>
          </div>
          <div>
            <div class="event-meta">${escapeHtml(event.event_id)}</div>
            <div class="event-text">${escapeHtml(event.text)}</div>
          </div>
        </article>
      `,
    )
    .join("");
  const lifecycle = data.learn.memory_lifecycle
    .map(
      (memory) => `
        <article class="memory-row">
          <div>
            <h3>${escapeHtml(memory.source)}</h3>
            <p class="memory-text">${escapeHtml(memory.text)}</p>
          </div>
          <span class="badge status-${escapeHtml(memory.status)}">
            ${escapeHtml(memory.status)}
          </span>
        </article>
      `,
    )
    .join("");
  return `
    <section class="stack">
      ${renderEvidenceBoundary()}
      ${renderHandoffReplay()}
      ${renderHandoffSimulator()}
      ${renderHeroStory()}
      <section class="view-grid">
        <div class="band">
          <h2>Observed Session</h2>
          <p class="goal">${escapeHtml(data.learn.goal)}</p>
          <div class="timeline">${timeline}</div>
        </div>
        <div class="stack">
          <div class="band">
            <h2>Memory Lifecycle</h2>
            <div class="stack">${lifecycle}</div>
          </div>
          <div class="band">
            <h2>Qwen Roles</h2>
            <div class="pipeline">
              ${["extract", "classify", "judge supersession", "embed", "rerank"]
                .map((step) => `<div class="pipeline-step">${escapeHtml(step)}</div>`)
                .join("")}
            </div>
          </div>
        </div>
      </section>
    </section>
  `;
}

function renderEvidenceBoundary() {
  const boundary = data.evidence_boundary;
  if (!boundary) return "";
  const sections = (boundary.sections || [])
    .map((section) => {
      const items = (section.items || [])
        .map((item) => `<li>${escapeHtml(item)}</li>`)
        .join("");
      return `
        <article class="boundary-card">
          <div class="small">${escapeHtml(section.id)}</div>
          <h3>${escapeHtml(section.label)}</h3>
          <ul class="proof-list">${items}</ul>
        </article>
      `;
    })
    .join("");
  const doNotClaim = (boundary.do_not_claim || [])
    .map((item) => `<span>${escapeHtml(item)}</span>`)
    .join("");
  return `
    <section class="evidence-boundary" aria-label="Evidence boundary">
      <div class="story-head">
        <div>
          <div class="eyebrow">MemoryAgent evidence boundary</div>
          <h2>${escapeHtml(boundary.title || "Evidence Boundary")}</h2>
          <p class="goal">${escapeHtml(boundary.summary || boundary.structural_claim || "")}</p>
        </div>
        <span class="badge status-gated">truthful local replay</span>
      </div>
      <div class="boundary-grid">${sections}</div>
      <div class="do-not-claim">
        <div class="small">What we do not claim</div>
        <div class="claim-tags">${doNotClaim}</div>
      </div>
    </section>
  `;
}

function renderHandoffReplay() {
  const replay = data.handoff_replay;
  if (!replay) return "";
  const activeStepId =
    replay.steps.some((step) => step.id === activeReplayStep)
      ? activeReplayStep
      : replay.default_step_id;
  const activeStep = replay.steps.find((step) => step.id === activeStepId) || replay.steps[0];
  const replayPlayLabel = replay.play_label || "Replay handoff";
  const controls = replay.steps
    .map(
      (step, index) => `
        <button type="button" class="replay-step" data-replay-step="${escapeHtml(step.id)}"
          aria-selected="${step.id === activeStepId}">
          <span>${index + 1}</span>
          ${escapeHtml(step.label)}
        </button>
      `,
    )
    .join("");
  const sources = activeStep.selected_sources
    .map((source) => `<span>${escapeHtml(source)}</span>`)
    .join("");
  const state =
    activeStep.variant_id === "recallpack"
      ? "passed"
      : "failed";
  const resultLabel =
    activeStep.result === "wrong_retry_patch"
      ? "wrong retry patch"
      : activeStep.result === "correct_retry_patch"
        ? "correct retry patch"
        : activeStep.result === "active_memory_pack_selected"
          ? "active memory pack"
          : activeStep.result.replaceAll("_", " ");
  return `
    <section class="handoff-replay" aria-label="Deterministic stale-memory failure replay">
      <div class="story-head">
        <div>
          <div class="eyebrow">MemoryAgent product moment</div>
          <h2>${escapeHtml(replay.title)}</h2>
          <p class="goal">${escapeHtml(replay.task)}</p>
        </div>
        <div class="replay-actions">
          <span class="badge status-gated">${escapeHtml(replay.mode_label || "Local replay")}</span>
          <button type="button" class="replay-primary" data-replay-step="${escapeHtml(replay.default_step_id)}">
            ${escapeHtml(replayPlayLabel)}
          </button>
        </div>
      </div>
      <div class="truth-banner">
        ${escapeHtml(replay.structural_claim || replay.truthfulness_note || "")}
      </div>
      <div class="replay-controls">${controls}</div>
      <article class="replay-panel ${state}">
        <div>
          <div class="small">${escapeHtml(activeStep.memory_status)}</div>
          <h3>${escapeHtml(activeStep.headline)}</h3>
          <p>${escapeHtml(activeStep.body)}</p>
        </div>
        <div class="replay-result">
          <div class="small">${escapeHtml(resultLabel)}</div>
          <div class="story-score">${escapeHtml(activeStep.hidden_tests)}</div>
          <div class="small">${escapeHtml(activeStep.patch_signal)}</div>
        </div>
        <div class="source-row">${sources}</div>
        <div class="small replay-evidence">${escapeHtml(activeStep.evidence)}</div>
      </article>
    </section>
  `;
}

function bindReplayControls() {
  app.querySelectorAll("[data-replay-step]").forEach((button) => {
    button.addEventListener("click", () => {
      setActiveReplayStep(button.dataset.replayStep);
    });
  });
}

function renderHandoffSimulator() {
  const simulator = data.handoff_simulator;
  if (!simulator) return "";
  const flow = simulator.flow
    .map(
      (step, index) => `
        <article class="sim-step">
          <div class="step-index">${index + 1}</div>
          <div>
            <h3>${escapeHtml(step.label)}</h3>
            <div class="small">${escapeHtml(step.evidence)}</div>
          </div>
        </article>
      `,
    )
    .join("");
  const reasons = simulator.why_it_wins
    .map((reason) => `<li>${escapeHtml(reason)}</li>`)
    .join("");
  const qwenStatus = (simulator.qwen_boundary.first_screen_lines || [])
    .map((line) => `<span>${escapeHtml(line)}</span>`)
    .join("");
  return `
    <section class="simulator-band" aria-label="First-run coding-agent handoff simulator">
      <div class="story-head">
        <div>
          <div class="eyebrow">coding-agent handoff</div>
          <h2>First-Run Handoff Simulator</h2>
          <p class="goal">${escapeHtml(simulator.task)}</p>
        </div>
        <div class="qwen-status-lines">${qwenStatus}</div>
      </div>
      <div class="sim-flow">${flow}</div>
      <div class="sim-branches">
        ${renderSimulatorBranch(simulator.baseline, "failed", "local replay stale raw history")}
        ${renderSimulatorBranch(simulator.recallpack, "passed", "active memory lifecycle pack")}
      </div>
      <ul class="proof-list sim-reasons">${reasons}</ul>
    </section>
  `;
}

function renderSimulatorBranch(branch, state, modeLabel) {
  const sources = branch.selected_sources
    .map((source) => `<span>${escapeHtml(source)}</span>`)
    .join("");
  return `
    <article class="sim-branch ${state}">
      <div>
        <div class="small">${escapeHtml(modeLabel)}</div>
        <h3>${escapeHtml(branch.label)}</h3>
      </div>
      <div class="story-score">${escapeHtml(branch.hidden_tests)}</div>
      <div class="small">${escapeHtml(branch.patch_signal)}</div>
      <div class="source-row">${sources}</div>
      <div class="small">${escapeHtml(branch.causal_reason)}</div>
    </article>
  `;
}

function renderHeroStory() {
  const story = data.hero_story;
  if (!story) return "";
  const judgeSummary = data.judge_first_screen || {};
  const comparison = (judgeSummary.comparison || [])
    .map(
      (item) => `
        <article class="judge-card">
          <div class="small">${escapeHtml(item.role)}</div>
          <h3>${escapeHtml(item.label)}</h3>
          <div class="story-score compact">${escapeHtml(item.downstream_tests)}</div>
          <div class="small">${escapeHtml(item.fairness_note)}</div>
        </article>
      `,
    )
    .join("");
  const qwenSummary = judgeSummary.qwen_load_bearing || {};
  const path = story.retrieval_path
    .map((step) => `<span>${escapeHtml(step)}</span>`)
    .join("");
  return `
    <section class="story-band" aria-label="RecallPack stale handoff proof">
      <div class="story-head">
        <div>
          <div class="eyebrow">MemoryAgent fixture demo</div>
          <h2>${escapeHtml(story.headline)}</h2>
          <p class="goal">${escapeHtml(story.failure_summary)}</p>
        </div>
        <span class="badge ${story.live_qwen_run ? "status-active" : "status-gated"}">
          standalone live API smoke ${escapeHtml(story.live_qwen_status)}
        </span>
      </div>
      <div class="judge-strip">${comparison}</div>
      <div class="story-grid">
        ${renderStoryOutcome(story.baseline, "failed")}
        ${renderStoryOutcome(story.recallpack, "passed")}
        <div class="story-pipeline">
          <div class="small">/compile path</div>
          <div class="path-row">${path}</div>
          <div class="small">
            superseded ${escapeHtml(story.memory_lifecycle_summary.superseded.join(", "))} /
            active ${escapeHtml(story.memory_lifecycle_summary.active.join(", "))}
          </div>
          <div class="small">
            Qwen model work ${escapeHtml((qwenSummary.model_work || []).join(" / "))};
            runtime work ${escapeHtml((qwenSummary.deterministic_runtime_work || []).join(" / "))}
          </div>
        </div>
      </div>
    </section>
  `;
}

function renderStoryOutcome(outcome, state) {
  const tests = outcome.test_summary;
  return `
    <article class="story-outcome ${state}">
      <div>
        <h3>${escapeHtml(outcome.label)}</h3>
        <div class="small">${escapeHtml(outcome.patch_signal)}</div>
      </div>
      <div class="story-score">${tests.passed}/${tests.total}</div>
      <div class="small">${escapeHtml(outcome.causal_reason)}</div>
    </article>
  `;
}

function renderRecall() {
  const variants = data.recall.variants
    .map((variant) => {
      const passCount = variant.metrics.hidden_test_pass_count;
      const pct = Math.round((passCount / 3) * 100);
      const downstream = variant.downstream;
      return `
        <article class="variant-row">
          <div>
            <h3>${escapeHtml(variant.label)}</h3>
            <div class="small">
              fixture tests ${passCount}/3 / stale leakage
              ${formatMetric(variant.metrics.stale_leakage_rate)}
            </div>
            <div class="small">
              downstream ${downstream.summary.passed}/3 / ${escapeHtml(downstream.causal_reason)}
            </div>
          </div>
          <div class="score-bar" aria-label="${escapeHtml(variant.label)} score">
            <span style="width: ${pct}%"></span>
          </div>
        </article>
      `;
    })
    .join("");
  const downstreamProofs = data.recall.variants
    .map((variant) => renderDownstreamProof(variant))
    .join("");
  const memories = data.recall.pack.memories
    .map(
      (memory) => `
        <article class="context-item">
          <div class="event-meta">${escapeHtml(memory.type)} - ${escapeHtml(memory.scope)}</div>
          <h3>${escapeHtml(memory.subject)}</h3>
          <div class="context-text">${escapeHtml(memory.text)}</div>
        </article>
      `,
    )
    .join("");
  const pipeline = data.recall.pipeline
    .map((step) => `<div class="pipeline-step">${escapeHtml(step)}</div>`)
    .join("");
  return `
    <section class="stack">
      <div class="band">
        <h2>Recall Pipeline</h2>
        <p class="goal">${escapeHtml(data.recall.goal)}</p>
        <div class="pipeline">${pipeline}</div>
      </div>
      <div class="view-grid">
        <div class="band">
          <h2>Baseline Comparison</h2>
          <div class="stack">${variants}</div>
        </div>
        <div class="band">
          <h2>PACK.md Memory Segment</h2>
          <div class="metrics-grid">
            ${metric("budget", data.recall.pack.budget_tokens)}
            ${metric("tokens", data.recall.pack.memory_segment_tokens)}
          </div>
          <div class="context-list">${memories}</div>
        </div>
      </div>
      <div class="band">
        <h2>Downstream Proof</h2>
        <div class="proof-grid">${downstreamProofs}</div>
      </div>
    </section>
  `;
}

function renderDownstreamProof(variant) {
  const downstream = variant.downstream;
  const tests = downstream.tests
    .map(
      (test) => `
        <li class="${test.passed ? "passed" : "failed"}">
          <span>${escapeHtml(test.name)}</span>
          <span>${test.passed ? "pass" : "fail"}</span>
        </li>
      `,
    )
    .join("");
  return `
    <article class="proof-card">
      <h3>${escapeHtml(variant.label)}</h3>
      <div class="small">${escapeHtml(downstream.causal_reason)}</div>
      <ul class="test-list">${tests}</ul>
      <pre class="diff-block">${escapeHtml(downstream.patch_diff)}</pre>
    </article>
  `;
}

function renderEvaluate() {
  const suite = data.evaluate.micro_suite;
  const matrixRows = Object.entries(suite.confusion_matrix)
    .map(([gold, row]) => {
      const cells = Object.values(row)
        .map((value) => `<td>${value}</td>`)
        .join("");
      return `<tr><td>${escapeHtml(gold)}</td>${cells}</tr>`;
    })
    .join("");
  const operations = Object.keys(suite.confusion_matrix.no_op);
  const headers = operations.map((op) => `<th>${escapeHtml(op)}</th>`).join("");
  const proof = data.deployment_proof;
  const evidence = suite.prediction_evidence;
  const qwenProof = data.qwen_load_bearing;
  const publicDeployment = proof.public_deployment || {};
  const nonActions = proof.non_actions
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");
  const deploymentLive = publicDeployment.url
    ? `
      <div class="deployment-live">
        <div>
          <div class="small">credential-free ECS runtime proof</div>
          <a href="${escapeHtml(publicDeployment.url)}" target="_blank" rel="noopener">
            ${escapeHtml(publicDeployment.url)}
          </a>
        </div>
        <div class="metrics-grid compact-grid">
          ${metric("judge smoke", publicDeployment.judge_smoke_status)}
          ${metric("container", publicDeployment.container)}
          ${metric("ports", publicDeployment.port_mapping)}
        </div>
      </div>
    `
    : "";
  return `
    <section class="stack">
      <div class="metrics-grid">
        ${metric("cases", suite.case_count)}
        ${metric("write tp", suite.raw_counts.tp)}
        ${metric("edge f1", suite.metrics.edge_f1)}
        ${metric("stale selected", suite.metrics.stale_selected_items)}
      </div>
      ${renderQwenLoadBearing(qwenProof)}
      ${renderGeneralizationFixtures(data.evaluate.generalization_fixtures)}
      <div class="view-grid">
        <div class="band">
          <h2>Confusion Matrix</h2>
          <table class="matrix">
            <thead>
              <tr><th>gold / predicted</th>${headers}</tr>
            </thead>
            <tbody>${matrixRows}</tbody>
          </table>
        </div>
        <div class="band">
          <h2>Evidence Suite</h2>
          <p class="goal">${escapeHtml(suite.positioning)}</p>
          <div class="metrics-grid">
            ${metric("edge correct", suite.edge_counts.correct)}
            ${metric("type accuracy", suite.metrics.memory_type_accuracy)}
            ${metric("recall at 512", suite.metrics.required_memory_recall_at_512)}
            ${metric("memory tokens", suite.metrics.memory_segment_tokens)}
          </div>
          <div class="metrics-grid compact-grid">
            ${metric("prediction source", evidence.prediction_source)}
            ${metric("runtime cases", evidence.case_count)}
            ${metric("fixture predictions used", evidence.used_fixture_predictions ? "yes" : "no")}
            ${metric("override count", evidence.decider_override_count)}
          </div>
        </div>
      </div>
      <div class="band">
        <h2>Alibaba Cloud Proof</h2>
        <div class="metrics-grid">
          ${metric("deployment replicas", proof.runtime_limits.deployment_replicas)}
          ${metric("app workers", proof.runtime_limits.application_workers)}
        </div>
        <p class="goal">${escapeHtml(proof.target)}</p>
        ${deploymentLive}
        <ul class="proof-list">${nonActions}</ul>
      </div>
    </section>
  `;
}

function renderGeneralizationFixtures(generalization) {
  if (!generalization) return "";
  const title =
    generalization.status === "curated_lifecycle_regression_fixtures"
      ? `${generalization.fixture_count || ""} Curated Lifecycle Fixtures`
      : "Lifecycle Fixture Proof";
  const fixtures = generalization.fixtures
    .map(
      (fixture) => `
        <article class="proof-card">
          <div>
            <div class="small">${escapeHtml(fixture.project_id)} / ${escapeHtml(fixture.component)}</div>
            <h3>${escapeHtml(fixture.goal)}</h3>
          </div>
          <div class="metrics-grid compact-grid trace-metrics">
            ${metric("baseline", fixture.baseline_downstream_tests)}
            ${metric("RecallPack", fixture.recallpack_downstream_tests)}
          </div>
          <div class="small">
            baseline ${escapeHtml(fixture.baseline_selected_sources.join(", "))}<br>
            recallpack ${escapeHtml(fixture.recallpack_selected_sources.join(", "))}
          </div>
        </article>
      `,
    )
    .join("");
  return `
    <div class="band">
      <h2>${title}</h2>
      <p class="goal">${escapeHtml(generalization.credibility_note)}</p>
      <div class="metrics-grid compact-grid">
        ${metric("fixtures", generalization.fixture_count)}
        ${metric("status", generalization.status)}
      </div>
      <div class="proof-grid">${fixtures}</div>
    </div>
  `;
}

function renderQwenLoadBearing(proof) {
  const usage = proof.actual_qwen_token_usage || {};
  const usageMetrics = Object.keys(usage).length
    ? `
      <div class="metrics-grid compact-grid">
        ${metric("memory tokens", usage.memory_decision_total_tokens || 0)}
        ${metric("embedding tokens", usage.embedding_total_tokens || 0)}
        ${metric("rerank tokens", usage.rerank_total_tokens || 0)}
      </div>
    `
    : "";
  const traces = proof.provider_traces
    .map(
      (trace) => `
        <article class="trace-card">
          <h3>${escapeHtml(trace.provider_role)}</h3>
          <div class="small">${escapeHtml(trace.model_name)}</div>
          <div class="small">${escapeHtml(trace.request_purpose)}</div>
          <div class="metrics-grid compact-grid trace-metrics">
            ${metric("inputs", trace.input_item_count)}
            ${metric("token est", trace.input_token_estimate)}
            ${metric("outputs", trace.output_item_count)}
            ${metric("live", trace.is_live ? "yes" : "no")}
          </div>
        </article>
      `,
    )
    .join("");
  const qwenWork = proof.qwen_model_work
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");
  const runtimeWork = proof.deterministic_runtime_work
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");
  return `
    <div class="band" id="qwen-provider-evidence">
      <h2>Qwen Provider Integration Evidence</h2>
      <div class="metrics-grid compact-grid">
        ${metric("live smoke", proof.live_qwen_run ? "passed" : "gated")}
        ${metric("trace records", proof.provider_traces.length)}
        ${metric("model roles", new Set(proof.provider_traces.map((trace) => trace.provider_role)).size)}
        ${metric("historical E2E", proof.stored_live_qwen_e2e_status || proof.live_qwen_e2e_status || "not claimed")}
        ${metric("Fresh live rerun", proof.fresh_m98_live_rerun_status || "gated_not_run")}
        ${metric("ProjectOdyssey E2E", proof.projectodyssey_live_e2e_status || "not_claimed")}
      </div>
      ${usageMetrics}
      <div class="trace-grid">${traces}</div>
      <div class="work-grid">
        <section>
          <h3>Qwen model work</h3>
          <ul class="proof-list">${qwenWork}</ul>
        </section>
        <section>
          <h3>Deterministic runtime work</h3>
          <ul class="proof-list">${runtimeWork}</ul>
        </section>
      </div>
      ${renderQwenTraceExplorer(proof)}
    </div>
  `;
}

function renderQwenTraceExplorer(proof) {
  const explorer = proof.trace_explorer;
  if (!explorer) return "";
  const roleSummary = explorer.role_summary || [];
  const stageSummary = explorer.stages || [];
  const selectedSourceList = explorer.selected_sources || [];
  const excludedSourceList = explorer.excluded_sources_checked || [];
  const safetyBoundary = explorer.safety_boundary || {};
  const roles = roleSummary
    .map(
      (role) => `
        <article class="trace-card">
          <h3>${escapeHtml(role.provider_role)}</h3>
          <div class="small">${escapeHtml(role.model_name)}</div>
          <div class="metrics-grid compact-grid trace-metrics">
            ${metric("records", role.trace_count)}
            ${metric("live records", role.live_trace_count)}
            ${metric("actual tokens", role.actual_tokens)}
            ${metric("outputs", role.output_item_count)}
          </div>
        </article>
      `,
    )
    .join("");
  const stages = stageSummary
    .map(
      (stage) => `
        <article class="trace-stage">
          <div class="small">${escapeHtml(stage.provider_role)}</div>
          <h3>${escapeHtml(stage.label)}</h3>
          <p>${escapeHtml(stage.model_work)}</p>
          <p>${escapeHtml(stage.mode_note || "")}</p>
          <div class="small">trace records ${escapeHtml(stage.trace_count)}</div>
        </article>
      `,
    )
    .join("");
  const selectedSources = selectedSourceList
    .map((source) => `<span>${escapeHtml(source)}</span>`)
    .join("");
  const excludedSources = excludedSourceList
    .map((source) => `<span>${escapeHtml(source)}</span>`)
    .join("");
  const safety = [];
  if (safetyBoundary.sanitized_trace_only) safety.push("sanitized trace only");
  if (safetyBoundary.no_credentials) safety.push("no credentials");
  if (safetyBoundary.prompts_redacted) safety.push("prompts redacted");
  if (safetyBoundary.local_demo_no_live_calls) {
    safety.push("local demo makes no live Qwen calls");
  }
  if (safetyBoundary.stored_trace_no_live_call) safety.push("checked-in file, no live call");
  return `
    <section class="trace-explorer">
      <div class="story-head">
        <div>
          <div class="eyebrow">reviewable provider trace</div>
          <h2>${escapeHtml(explorer.display_title || "Stored Live Qwen Trace")}</h2>
          <p class="goal">${escapeHtml(explorer.source)}</p>
        </div>
        <div class="qwen-status-lines">
          <span class="badge status-active">${escapeHtml(explorer.status)}</span>
          <span>checked-in file, no live call</span>
        </div>
      </div>
      <div class="metrics-grid compact-grid">
        ${metric("observed events", explorer.observed_event_count)}
        ${metric("selected", selectedSourceList.length)}
        ${metric("excluded stale", excludedSourceList.length)}
        ${metric("downstream", explorer.downstream_summary)}
      </div>
      <div class="trace-stage-grid">${stages}</div>
      <div class="trace-grid">${roles}</div>
      <div class="trace-source-grid">
        <section>
          <h3>Selected sources</h3>
          <div class="source-row">${selectedSources}</div>
        </section>
        <section>
          <h3>Excluded stale sources</h3>
          <div class="source-row">${excludedSources}</div>
        </section>
      </div>
      <div class="small">${escapeHtml(safety.join(" / "))}</div>
      <div class="small">downstream patch generation boundary: local deterministic context-keyed patch provider is used for the credential-free demo; stored live Qwen E2E trace records the model-in-the-loop patch-generation run.</div>
    </section>
  `;
}

function render() {
  renderTabs();
  if (activeView === "learn") app.innerHTML = renderLearn();
  if (activeView === "recall") app.innerHTML = renderRecall();
  if (activeView === "evaluate") app.innerHTML = renderEvaluate();
  bindReplayControls();
  scrollToRequestedSection();
}

render();
