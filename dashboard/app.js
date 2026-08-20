"use strict";

// Backend base URL. Edit this if the API is running somewhere other than
// the default `uvicorn digital_twin.main:app --reload --app-dir src`.
const API_BASE = "http://127.0.0.1:8000";

// This dashboard never computes twin_id, mastery, priority, evidence, or any
// prediction itself — every value rendered below comes directly from an API
// response, or (for the frozen BKT research table only) from constants that
// mirror an already-completed, frozen experiment (see RESEARCH_RESULTS
// below) — never recomputed or re-fetched live. It only calls:
//   GET  /classrooms/resolve
//   GET  /classrooms/{twin_id}/decision-support
//   GET  /classrooms/{twin_id}/state          (Knowledge Tracing panel)
//   POST /classrooms/{twin_id}/decision-support/explanation
//   GET  /demo/classroom-scenario              (Smart Classroom panel)
//   GET  /demo/context-signals                 (Benchmark Evidence panel)
//   GET  /students/oulad-demo                  (Student Twin panel)
//
// The real decision-support panel and its GET/POST calls above are completely
// unaffected by Demo Mode: they are identical whether the toggle is on or off,
// except that the explanation POST also carries `mode=demo`/`mode=real`.
//
// /demo/classroom-scenario returns FABRICATED data (provenance="synthetic_demo")
// deliberately scoped to the currently loaded class_id/source_dataset — that
// association is intentional (it's the whole demo narrative), disclosed once
// via a single banner rather than repeated per value.
//
// /demo/context-signals returns REAL xAPI-Edu-Data/UCI Occupancy data but carries
// no classroom identity at all and is rendered in a visually secondary panel,
// captioned as unrelated to, and not the source of, the synthetic scenario above.
//
// /students/oulad-demo returns REAL OULAD data for one OULAD student, with no
// identity relationship to the ASSISTments classroom loaded above — the Student
// Twin panel is deliberately independent of the classroom selector.

// Frozen BKT knowledge-tracing experiment results (student-level train/val/test
// split, 11,828 held-out one-step-ahead predictions, 400 test students, 281
// skills). These are constants, not a live computation — this dashboard never
// retrains or re-evaluates any model; see CLAUDE.md and the experiment's own
// research writeup for the protocol. Log Loss is the primary metric.
const RESEARCH_RESULTS = [
  { name: "Persistence baseline", logLoss: 5.6257, brier: 0.3078, rmse: 0.5548, accuracy: 0.6645, auc: 0.6387 },
  { name: "Empirical-rate baseline", logLoss: 0.6394, brier: 0.2236, rmse: 0.4728, accuracy: 0.6633, auc: 0.5000 },
  { name: "Literature-default BKT", logLoss: 0.6341, brier: 0.2167, rmse: 0.4655, accuracy: 0.6529, auc: 0.6624 },
  { name: "Train-fitted BKT", logLoss: 0.5968, brier: 0.2045, rmse: 0.4522, accuracy: 0.6864, auc: 0.6731 },
  { name: "BKT + historical features (LR)", logLoss: 0.5825, brier: 0.1983, rmse: 0.4453, accuracy: 0.7005, auc: 0.6995 },
  { name: "Historical features (GBM)", logLoss: 0.5779, brier: 0.1966, rmse: 0.4434, accuracy: 0.7047, auc: 0.7056 },
];

const classIdSelect = document.getElementById("class-id-select");
const classIdCustom = document.getElementById("class-id-custom");
const customLabel = document.getElementById("custom-label");
const classroomForm = document.getElementById("classroom-form");
const loadButton = document.getElementById("load-button");
const selectorStatus = document.getElementById("selector-status");
const demoModeToggle = document.getElementById("demo-mode-toggle");

const decisionSupportPanel = document.getElementById("decision-support-panel");
const splitRow = document.getElementById("split-row");
const llmPanel = document.getElementById("llm-panel");
const llmButton = document.getElementById("llm-button");
const llmLoading = document.getElementById("llm-loading");
const llmError = document.getElementById("llm-error");
const llmResult = document.getElementById("llm-result");

const scenarioPanel = document.getElementById("scenario-panel");
const scenarioBanner = document.getElementById("scenario-banner");
const benchmarkPanel = document.getElementById("benchmark-panel");

const ouladSelect = document.getElementById("oulad-select");
const ouladCustomFields = document.getElementById("oulad-custom-fields");
const ouladForm = document.getElementById("oulad-form");
const ouladLoadButton = document.getElementById("oulad-load-button");
const ouladStatus = document.getElementById("oulad-status");
const ouladResult = document.getElementById("oulad-result");

let currentTwinId = null;
let currentClassId = null;
let currentSourceDataset = "assistments";

classIdSelect.addEventListener("change", () => {
  const isCustom = classIdSelect.value === "__custom__";
  customLabel.hidden = !isCustom;
  classIdCustom.hidden = !isCustom;
});

ouladSelect.addEventListener("change", () => {
  ouladCustomFields.hidden = ouladSelect.value !== "__custom__";
});

function selectedClassId() {
  if (classIdSelect.value === "__custom__") {
    const value = Number(classIdCustom.value);
    return Number.isInteger(value) && value > 0 ? value : null;
  }
  return Number(classIdSelect.value);
}

function selectedOuladStudent() {
  if (ouladSelect.value === "__custom__") {
    const idStudent = Number(document.getElementById("oulad-id-student").value);
    const codeModule = document.getElementById("oulad-code-module").value.trim();
    const codePresentation = document.getElementById("oulad-code-presentation").value.trim();
    if (!Number.isInteger(idStudent) || idStudent <= 0 || !codeModule || !codePresentation) {
      return null;
    }
    return { idStudent, codeModule, codePresentation };
  }
  const [idStudent, codeModule, codePresentation] = ouladSelect.value.split("|");
  return { idStudent: Number(idStudent), codeModule, codePresentation };
}

async function fetchJson(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (networkError) {
    throw new Error(
      `Could not reach the backend at ${API_BASE}. Is it running? (${networkError.message})`
    );
  }
  let body = null;
  try {
    body = await response.json();
  } catch (_parseError) {
    // no JSON body — fall through, response.ok check below still applies
  }
  if (!response.ok) {
    const detail = body && body.detail ? body.detail : `HTTP ${response.status}`;
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return body;
}

function setText(id, text) {
  document.getElementById(id).textContent = text;
}

function renderList(id, items) {
  const el = document.getElementById(id);
  el.innerHTML = "";
  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = item;
    el.appendChild(li);
  }
}

function renderDecisionSupport(data) {
  setText(
    "ds-source-line",
    `twin_id ${data.twin_id} — ${data.source_dataset} class_id ${data.source_class_id}`
  );
  setText("ds-summary", data.summary);
  setText("ds-priority-skill", data.priority_skill || "No reliable priority skill available yet.");
  setText("ds-rationale", data.rationale);

  const resourcesBody = document.getElementById("ds-resources-body");
  resourcesBody.innerHTML = "";
  const resourcesEmpty = document.getElementById("ds-resources-empty");
  if (data.recommended_resources.length === 0) {
    resourcesEmpty.hidden = false;
  } else {
    resourcesEmpty.hidden = true;
    for (const resource of data.recommended_resources) {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>${resource.problem_id}</td>
        <td>${(resource.mean_correct * 100).toFixed(1)}%</td>
        <td>${resource.student_answer_count}</td>
      `;
      resourcesBody.appendChild(row);
    }
  }

  renderList("ds-evidence", data.evidence);
  renderList("ds-limitations", data.limitations);

  const contextAvailable = document.getElementById("ds-context-available");
  const contextUnavailable = document.getElementById("ds-context-unavailable");
  if (data.context_signals && data.context_signals.length > 0) {
    contextAvailable.hidden = false;
    contextUnavailable.hidden = true;
    setText("ds-context-note", data.context_note || "");
    const signalsList = document.getElementById("ds-context-signals");
    signalsList.innerHTML = "";
    for (const signal of data.context_signals) {
      const li = document.createElement("li");
      li.textContent = `[${signal.source_dataset}] ${signal.metric_name} = ${signal.value} — ${signal.scope_description}`;
      signalsList.appendChild(li);
    }
  } else {
    contextAvailable.hidden = true;
    contextUnavailable.hidden = false;
  }

  decisionSupportPanel.hidden = false;

  // The Knowledge Tracing panel reuses this same response's priority_skill
  // rather than re-deriving or re-fetching it — one source of truth.
  setText(
    "kt-priority-skill",
    data.priority_skill
      ? `${data.priority_skill} — ${data.rationale}`
      : "No reliable priority skill available yet."
  );
}

function renderKnowledgeTracingState(data) {
  setText("kt-students", `${data.students_used} / ${data.students_eligible}`);
  const topicIds = Object.keys(data.average_mastery_by_topic);
  setText("kt-skills", String(topicIds.length));
  const totalAttempts = Object.values(data.topic_observation_counts).reduce((a, b) => a + b, 0);
  setText("kt-attempts", String(totalAttempts));

  const body = document.getElementById("kt-mastery-body");
  const empty = document.getElementById("kt-mastery-empty");
  body.innerHTML = "";
  if (topicIds.length === 0) {
    empty.hidden = false;
  } else {
    empty.hidden = true;
    for (const topicId of topicIds) {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>${topicId}</td>
        <td>${(data.average_mastery_by_topic[topicId] * 100).toFixed(1)}%</td>
        <td>${data.topic_observation_counts[topicId] ?? 0}</td>
      `;
      body.appendChild(row);
    }
  }
}

async function loadKnowledgeTracingPanel(twinId, classId) {
  try {
    const state = await fetchJson(
      `${API_BASE}/classrooms/${twinId}/state?class_id=${classId}`
    );
    renderKnowledgeTracingState(state);
  } catch (error) {
    setText("kt-priority-skill", `Learning state unavailable: ${error.message}`);
  }
}

function renderResearchTable() {
  const tbody = document.querySelector("#research-table tbody");
  tbody.innerHTML = "";
  for (const row of RESEARCH_RESULTS) {
    const tr = document.createElement("tr");
    if (row.name === "Historical features (GBM)") {
      tr.classList.add("research-best-row");
    }
    tr.innerHTML = `
      <td>${row.name}</td>
      <td><strong>${row.logLoss.toFixed(4)}</strong></td>
      <td>${row.brier.toFixed(4)}</td>
      <td>${row.rmse.toFixed(4)}</td>
      <td>${(row.accuracy * 100).toFixed(1)}%</td>
      <td>${row.auc.toFixed(4)}</td>
    `;
    tbody.appendChild(tr);
  }
}

function renderScenarioPanel(data) {
  scenarioBanner.textContent = "DEMONSTRATION SCENARIO";
  setText("scenario-note", data.scenario_note);

  const env = data.environment;
  setText("scenario-temperature", `${env.temperature_c.toFixed(1)} °C`);
  setText("scenario-humidity", `${env.humidity_pct.toFixed(1)}%`);
  setText("scenario-co2", `${env.co2_ppm} ppm`);
  setText("scenario-occupancy", env.occupied ? "Occupied" : "Unoccupied");

  const engagement = data.engagement;
  setText("scenario-raised-hands", String(engagement.raised_hands));
  setText("scenario-visited-resources", String(engagement.visited_resources));
  setText("scenario-announcements", String(engagement.announcements_view));
  setText("scenario-discussion", String(engagement.discussion));

  const absenceRisk = data.absence_risk;
  setText(
    "scenario-absence-risk",
    `${(absenceRisk.absence_risk_indicator * 100).toFixed(0)}% predicted absence risk`
  );

  scenarioPanel.hidden = false;
}

async function loadScenarioPanel(classId, sourceDataset) {
  try {
    const data = await fetchJson(
      `${API_BASE}/demo/classroom-scenario?class_id=${classId}&source_dataset=${sourceDataset}`
    );
    renderScenarioPanel(data);
  } catch (error) {
    scenarioBanner.textContent = `Synthetic scenario unavailable: ${error.message}`;
    scenarioPanel.hidden = false;
  }
}

function renderBenchmarkPanel(data) {
  setText(
    "demo-xapi-source-line",
    `xAPI-Edu-Data record_id ${data.xapi_record_id} (not linked to any classroom)`
  );
  setText("demo-xapi-note", data.xapi_note);

  const xapiSignalsList = document.getElementById("demo-xapi-signals");
  xapiSignalsList.innerHTML = "";
  const allXapiSignals = data.xapi_absence_risk_signal
    ? [...data.xapi_context_signals, data.xapi_absence_risk_signal]
    : data.xapi_context_signals;
  for (const signal of allXapiSignals) {
    const li = document.createElement("li");
    li.textContent =
      `[BENCHMARK — ${signal.source_dataset}] ${signal.metric_name} = ${signal.value} — ` +
      `${signal.scope_description}`;
    xapiSignalsList.appendChild(li);
  }

  const occupancy = data.occupancy_benchmark;
  setText("demo-occupancy-description", occupancy.description);

  const headline = occupancy.headline_metrics;
  setText("demo-occ-headline-accuracy", headline.accuracy.toFixed(3));
  setText("demo-occ-headline-precision", headline.precision.toFixed(3));
  setText("demo-occ-headline-recall", headline.recall.toFixed(3));
  setText("demo-occ-headline-f1", headline.f1.toFixed(3));
  setText("demo-occ-headline-roc-auc", headline.roc_auc.toFixed(3));

  const transition = occupancy.transition_event_metrics;
  setText(
    "demo-occ-transition-label",
    `Transition events only (${occupancy.transition_event_count})`
  );
  if (transition) {
    setText("demo-occ-transition-accuracy", transition.accuracy.toFixed(3));
    setText("demo-occ-transition-precision", transition.precision.toFixed(3));
    setText("demo-occ-transition-recall", transition.recall.toFixed(3));
    setText("demo-occ-transition-f1", transition.f1.toFixed(3));
    setText("demo-occ-transition-roc-auc", transition.roc_auc.toFixed(3));
  } else {
    for (const id of [
      "demo-occ-transition-accuracy",
      "demo-occ-transition-precision",
      "demo-occ-transition-recall",
      "demo-occ-transition-f1",
      "demo-occ-transition-roc-auc",
    ]) {
      setText(id, "n/a");
    }
  }

  renderList("demo-occupancy-limitations", occupancy.limitations);

  benchmarkPanel.hidden = false;
}

async function loadBenchmarkPanel() {
  try {
    const data = await fetchJson(`${API_BASE}/demo/context-signals`);
    renderBenchmarkPanel(data);
  } catch (error) {
    setText("demo-xapi-note", `Benchmark evidence unavailable: ${error.message}`);
    benchmarkPanel.hidden = false;
  }
}

function hideDemoPanels() {
  scenarioPanel.hidden = true;
}

demoModeToggle.addEventListener("change", () => {
  if (!demoModeToggle.checked) {
    hideDemoPanels();
    return;
  }
  if (currentClassId !== null) {
    loadScenarioPanel(currentClassId, currentSourceDataset);
  }
});

function resetLlmPanel() {
  llmPanel.hidden = false;
  llmLoading.hidden = true;
  llmError.hidden = true;
  llmResult.hidden = true;
  llmButton.disabled = false;
  llmButton.textContent = "Generate LLM explanation";
}

function renderLlmExplanation(data) {
  setText("llm-mode", data.mode === "demo" ? "Demonstration mode" : "Real classroom");
  setText("llm-summary", data.summary);
  setText("llm-reasoning", data.reasoning);
  renderList("llm-actions", data.recommended_actions);
  renderList("llm-evidence", data.evidence_used);
  renderList("llm-limitations", data.limitations);
  llmResult.hidden = false;
}

classroomForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const classId = selectedClassId();
  if (classId === null) {
    selectorStatus.textContent = "Enter a valid, positive class_id.";
    return;
  }

  loadButton.disabled = true;
  selectorStatus.textContent = "Resolving classroom identity…";
  decisionSupportPanel.hidden = true;
  splitRow.hidden = true;
  llmPanel.hidden = true;

  try {
    const resolved = await fetchJson(
      `${API_BASE}/classrooms/resolve?class_id=${classId}&source_dataset=assistments`
    );
    currentTwinId = resolved.twin_id;
    currentClassId = classId;
    currentSourceDataset = resolved.source_dataset;

    selectorStatus.textContent = "Loading deterministic decision support…";
    const decisionSupport = await fetchJson(
      `${API_BASE}/classrooms/${currentTwinId}/decision-support?class_id=${classId}`
    );
    renderDecisionSupport(decisionSupport);
    resetLlmPanel();
    splitRow.hidden = false;
    selectorStatus.textContent = `Loaded classroom ${classId}.`;

    loadKnowledgeTracingPanel(currentTwinId, classId);

    if (demoModeToggle.checked) {
      loadScenarioPanel(currentClassId, currentSourceDataset);
    }
  } catch (error) {
    selectorStatus.textContent = `Failed to load classroom: ${error.message}`;
  } finally {
    loadButton.disabled = false;
  }
});

llmButton.addEventListener("click", async () => {
  if (!currentTwinId || currentClassId === null) {
    return;
  }

  llmButton.disabled = true;
  llmButton.textContent = "Generating…";
  llmLoading.hidden = false;
  llmError.hidden = true;
  llmResult.hidden = true;

  const mode = demoModeToggle.checked ? "demo" : "real";

  try {
    const explanation = await fetchJson(
      `${API_BASE}/classrooms/${currentTwinId}/decision-support/explanation?class_id=${currentClassId}&mode=${mode}`,
      { method: "POST" }
    );
    renderLlmExplanation(explanation);
  } catch (error) {
    if (error.status === 503) {
      llmError.textContent =
        `LLM explanation unavailable: ${error.message}. The deterministic result above ` +
        "is unaffected — configure ANTHROPIC_API_KEY in .env and restart the backend to enable this.";
    } else {
      llmError.textContent = `LLM explanation request failed: ${error.message}`;
    }
    llmError.hidden = false;
  } finally {
    llmLoading.hidden = true;
    llmButton.disabled = false;
    llmButton.textContent = "Generate LLM explanation";
  }
});

function renderOuladResult(data) {
  setText("oulad-note", data.note);

  const perf = data.assessment_performance;
  const performanceSummary = document.getElementById("oulad-assessment-summary");
  if (perf.total_results === 0) {
    performanceSummary.textContent = "No recorded assessment results for this student/course.";
  } else {
    const avg = perf.average_score !== null ? perf.average_score.toFixed(1) : "n/a";
    const recent = perf.recent_average_score !== null ? perf.recent_average_score.toFixed(1) : "n/a";
    performanceSummary.textContent =
      `${perf.total_results} result(s) — average score ${avg}, recent average ${recent}` +
      (perf.trend ? `, trend: ${perf.trend}` : "");
  }

  const dropoutValue = document.getElementById("oulad-dropout-value");
  if (data.dropout_risk) {
    dropoutValue.textContent = `${(data.dropout_risk.dropout_probability * 100).toFixed(0)}% predicted dropout probability`;
  } else {
    dropoutValue.textContent = "Not available";
  }
  setText("oulad-dropout-note", data.dropout_risk_note);

  const performanceValue = document.getElementById("oulad-performance-value");
  if (data.performance_prediction) {
    performanceValue.textContent = `${(data.performance_prediction.pass_probability * 100).toFixed(0)}% predicted pass probability`;
  } else {
    performanceValue.textContent = "Not available";
  }
  setText("oulad-performance-note", data.performance_prediction_note);

  ouladResult.hidden = false;
}

async function loadOuladStudent() {
  const selection = selectedOuladStudent();
  if (selection === null) {
    ouladStatus.textContent = "Enter a valid id_student, code_module, and code_presentation.";
    return;
  }

  ouladLoadButton.disabled = true;
  ouladStatus.textContent = "Loading OULAD student…";
  ouladResult.hidden = true;

  try {
    const data = await fetchJson(
      `${API_BASE}/students/oulad-demo?id_student=${selection.idStudent}` +
        `&code_module=${encodeURIComponent(selection.codeModule)}` +
        `&code_presentation=${encodeURIComponent(selection.codePresentation)}`
    );
    renderOuladResult(data);
    ouladStatus.textContent = "";
  } catch (error) {
    ouladStatus.textContent = `Failed to load OULAD student: ${error.message}`;
  } finally {
    ouladLoadButton.disabled = false;
  }
}

ouladForm.addEventListener("submit", (event) => {
  event.preventDefault();
  loadOuladStudent();
});

renderResearchTable();
loadBenchmarkPanel();
loadOuladStudent();
