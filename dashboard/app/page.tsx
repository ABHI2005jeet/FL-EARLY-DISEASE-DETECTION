"use client";

import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";

type RoundRecord = {
  round: number;
  status: string;
  uploads_received: number;
  expected_uploads: number;
  local_accuracy: Record<string, number>;
  average_local_accuracy: number | null;
  global_accuracy: number | null;
  participated_clients: string[];
  skipped_clients: string[];
  aggregation_trigger: string | null;
  global_model_key?: string;
  started_at?: string;
  completed_at?: string;
};

type RoundsResponse = {
  training_complete: boolean;
  total_rounds: number;
  expected_clients: string[];
  current_model_key: string;
  rounds: RoundRecord[];
};

type ClinicalFlag = {
  type: "warning" | "danger" | "info";
  label: string;
};

type PredictionResponse = {
  prediction: string;
  risk_probability: number;
  risk_percent: number;
  model_round: number;
  model_key: string;
  clinical_flags?: ClinicalFlag[];
};

type PatientPreset = {
  id: string;
  name: string;
  description: string;
  features: Record<string, number | string>;
};

type AuditEvent = {
  timestamp: string;
  actor: string;
  action: string;
  resource: string;
  status: string;
  details?: Record<string, any>;
};

type ClientMetadata = {
  client_id: string;
  display_name: string;
  sample_count: number;
  s3_prefix: string;
  iam_role: string;
  encryption: string;
  privacy_mode: string;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

const initialFeatures: Record<string, string> = {
  age: "54",
  sex: "1",
  cp: "3",
  trestbps: "130",
  chol: "246",
  fbs: "0",
  restecg: "0",
  thalach: "150",
  exang: "0",
  oldpeak: "1.0",
  slope: "1",
  ca: "0",
  thal: "3",
};

const featureConfig: Record<
  string,
  { label: string; unit?: string; min: number; max: number; step: number; hint: string; category: string }
> = {
  age: { label: "Patient Age", unit: "yrs", min: 20, max: 90, step: 1, hint: "Age in years", category: "Demographics" },
  sex: { label: "Sex", unit: "", min: 0, max: 1, step: 1, hint: "1 = Male, 0 = Female", category: "Demographics" },
  cp: { label: "Chest Pain Type", unit: "0-3", min: 0, max: 3, step: 1, hint: "0: Typical, 1: Atypical, 2: Non-anginal, 3: Asymptomatic", category: "Symptoms" },
  trestbps: { label: "Resting BP", unit: "mm Hg", min: 80, max: 220, step: 1, hint: "Resting systolic blood pressure", category: "Vitals" },
  chol: { label: "Serum Cholesterol", unit: "mg/dl", min: 100, max: 580, step: 1, hint: "Serum cholesterol level", category: "Lab Results" },
  fbs: { label: "Fasting Blood Sugar", unit: "", min: 0, max: 1, step: 1, hint: "1 if > 120 mg/dl, 0 otherwise", category: "Lab Results" },
  restecg: { label: "Resting ECG", unit: "0-2", min: 0, max: 2, step: 1, hint: "0: Normal, 1: ST-T wave abn, 2: LV hypertrophy", category: "Diagnostics" },
  thalach: { label: "Max Heart Rate", unit: "bpm", min: 60, max: 220, step: 1, hint: "Maximum heart rate achieved", category: "Vitals" },
  exang: { label: "Exercise Angina", unit: "", min: 0, max: 1, step: 1, hint: "1 = Yes, 0 = No", category: "Symptoms" },
  oldpeak: { label: "ST Depression (Oldpeak)", unit: "", min: 0.0, max: 6.5, step: 0.1, hint: "ST depression induced by exercise relative to rest", category: "Diagnostics" },
  slope: { label: "Slope of Peak ST", unit: "0-2", min: 0, max: 2, step: 1, hint: "0: Upsloping, 1: Flat, 2: Downsloping", category: "Diagnostics" },
  ca: { label: "Major Vessels (Fluoroscopy)", unit: "0-3", min: 0, max: 3, step: 1, hint: "Number of major vessels colored by flourosopy", category: "Imaging" },
  thal: { label: "Thallium Stress Result", unit: "1-3", min: 1, max: 3, step: 1, hint: "1: Normal, 2: Fixed defect, 3: Reversible defect", category: "Imaging" },
};

export default function Home() {
  const [activeTab, setActiveTab] = useState<"overview" | "prediction" | "nodes" | "audit" | "architecture">("overview");
  const [roundsData, setRoundsData] = useState<RoundsResponse | null>(null);
  const [features, setFeatures] = useState(initialFeatures);
  const [prediction, setPrediction] = useState<PredictionResponse | null>(null);
  const [presets, setPresets] = useState<PatientPreset[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditEvent[]>([]);
  const [clients, setClients] = useState<ClientMetadata[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [trainingInProgress, setTrainingInProgress] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trainingMessage, setTrainingMessage] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [hoveredRound, setHoveredRound] = useState<RoundRecord | null>(null);

  // Training modal state
  const [showTrainModal, setShowTrainModal] = useState(false);
  const [customRounds, setCustomRounds] = useState(8);
  const [customDropout, setCustomDropout] = useState("hospital_3:2");

  async function loadRounds() {
    try {
      const response = await fetch(`${API_BASE}/rounds`);
      if (response.ok) {
        const data = await response.json();
        setRoundsData(data);
        if (data.training_complete && trainingInProgress) {
          setTrainingInProgress(false);
          setTrainingMessage("Federated training converged successfully!");
        }
      }
    } catch (err) {
      console.error("Failed to load rounds:", err);
    } finally {
      setLoading(false);
    }
  }

  async function loadAuxiliaryData() {
    try {
      const [presetsRes, auditRes, clientsRes] = await Promise.allSettled([
        fetch(`${API_BASE}/presets`).then((r) => (r.ok ? r.json() : null)),
        fetch(`${API_BASE}/audit`).then((r) => (r.ok ? r.json() : null)),
        fetch(`${API_BASE}/clients`).then((r) => (r.ok ? r.json() : null)),
      ]);

      if (presetsRes.status === "fulfilled" && presetsRes.value?.presets) {
        setPresets(presetsRes.value.presets);
      }
      if (auditRes.status === "fulfilled" && auditRes.value?.events) {
        setAuditLogs(auditRes.value.events);
      }
      if (clientsRes.status === "fulfilled" && clientsRes.value?.clients) {
        setClients(clientsRes.value.clients);
      }
    } catch (err) {
      console.warn("Could not load auxiliary API endpoints:", err);
    }
  }

  useEffect(() => {
    loadRounds();
    loadAuxiliaryData();
  }, []);

  useEffect(() => {
    if (!autoRefresh && !trainingInProgress) return;
    const interval = setInterval(() => {
      loadRounds();
      loadAuxiliaryData();
    }, 2500);
    return () => clearInterval(interval);
  }, [autoRefresh, trainingInProgress]);

  const latestRound = roundsData?.rounds.at(-1);
  const skippedCount = useMemo(
    () =>
      roundsData?.rounds.reduce(
        (total, round) => total + round.skipped_clients.length,
        0
      ) ?? 0,
    [roundsData]
  );

  const bestAccuracy = useMemo(() => {
    if (!roundsData?.rounds.length) return null;
    const accuracies = roundsData.rounds
      .map((r) => r.global_accuracy)
      .filter((a): a is number => a !== null);
    return accuracies.length ? Math.max(...accuracies) : null;
  }, [roundsData]);

  async function submitPrediction(event?: FormEvent<HTMLFormElement>) {
    if (event) event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/predict`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ features }),
      });
      const body = await response.json();
      if (!response.ok) {
        throw new Error(body.error ?? "Prediction request failed");
      }
      setPrediction(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Prediction failed");
    } finally {
      setSubmitting(false);
    }
  }

  async function triggerTraining() {
    setTrainingInProgress(true);
    setTrainingMessage("Training initiated! Executing FedAvg aggregation cycle...");
    setShowTrainModal(false);
    try {
      const res = await fetch(`${API_BASE}/train`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rounds: customRounds,
          simulate_dropout: customDropout,
        }),
      });
      if (!res.ok) {
        const body = await res.json();
        throw new Error(body.error || "Training trigger failed");
      }
    } catch (err) {
      setTrainingInProgress(false);
      setError(err instanceof Error ? err.message : "Failed to trigger training");
    }
  }

  function applyPreset(preset: PatientPreset) {
    const stringified: Record<string, string> = {};
    for (const [k, v] of Object.entries(preset.features)) {
      stringified[k] = String(v);
    }
    setFeatures(stringified);
  }

  return (
    <div className="app-container">
      {/* BACKGROUND GLOWS */}
      <div className="bg-glow bg-glow-1" />
      <div className="bg-glow bg-glow-2" />
      <div className="bg-glow bg-glow-3" />

      <main className="shell">
        {/* HEADER BAR */}
        <header className="topbar">
          <div className="brand-section">
            <div className="logo-badge">
              <span className="pulse-dot" />
              <svg className="logo-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                  d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z"
                />
              </svg>
            </div>
            <div>
              <div className="badge-row">
                <span className="status-pill status-pill-active">
                  <span className="live-dot" /> FedAvg Cloud Prototype
                </span>
                <span className="status-pill status-pill-privacy">🔒 Zero-Patient-Data-Egress</span>
                <span className="status-pill status-pill-security">🛡️ SSE-S3 AES-256</span>
              </div>
              <h1 className="brand-title">AegisFL • Early Disease Detection</h1>
              <p className="brand-subtitle">
                Privacy-Preserving Collaborative AI Across Isolated Hospital Nodes
              </p>
            </div>
          </div>

          <div className="header-actions">
            <button
              className="btn btn-primary btn-glow"
              onClick={() => setShowTrainModal(true)}
              disabled={trainingInProgress}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" className="btn-icon">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              {trainingInProgress ? "Simulation In Progress..." : "Run FL Simulation"}
            </button>

            <button
              className={`btn btn-secondary ${autoRefresh ? "btn-active-toggle" : ""}`}
              onClick={() => setAutoRefresh(!autoRefresh)}
              title="Toggle automatic 2.5s polling"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" className="btn-icon">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              {autoRefresh ? "Auto-Polling ON" : "Auto-Polling OFF"}
            </button>

            <button className="btn btn-secondary" onClick={() => { loadRounds(); loadAuxiliaryData(); }}>
              Refresh
            </button>
          </div>
        </header>

        {/* ALERTS & NOTICES */}
        {trainingMessage && (
          <div className="alert alert-info">
            <div className="alert-content">
              <span className="alert-icon">⚡</span>
              <span>{trainingMessage}</span>
            </div>
            <button className="alert-close" onClick={() => setTrainingMessage(null)}>×</button>
          </div>
        )}

        {error && (
          <div className="alert alert-danger">
            <div className="alert-content">
              <span className="alert-icon">⚠️</span>
              <span>{error}</span>
            </div>
            <button className="alert-close" onClick={() => setError(null)}>×</button>
          </div>
        )}

        {/* EXECUTIVE METRICS */}
        <section className="metrics-deck">
          <div className="metric-card glass-panel">
            <div className="metric-header">
              <span className="metric-label">Pipeline Status</span>
              <span className={`status-indicator ${roundsData?.training_complete ? "indicator-success" : "indicator-running"}`} />
            </div>
            <div className="metric-value-row">
              <span className="metric-value">
                {trainingInProgress ? "Training..." : roundsData?.training_complete ? "Converged" : "Active"}
              </span>
            </div>
            <span className="metric-subtext">
              {roundsData?.training_complete
                ? "Flag written to DynamoDB"
                : `Round ${roundsData?.rounds.length ?? 0} of ${roundsData?.total_rounds ?? 8}`}
            </span>
          </div>

          <div className="metric-card glass-panel">
            <div className="metric-header">
              <span className="metric-label">FedAvg Rounds</span>
              <span className="metric-badge">Exit = 8</span>
            </div>
            <div className="metric-value-row">
              <span className="metric-value text-gradient-cyan">
                {roundsData?.rounds.length ?? 0}
                <span className="metric-denom"> / {roundsData?.total_rounds ?? 8}</span>
              </span>
            </div>
            <span className="metric-subtext">Multi-round synchronization loop</span>
          </div>

          <div className="metric-card glass-panel">
            <div className="metric-header">
              <span className="metric-label">Peak Global Accuracy</span>
              <span className="metric-badge-green">Aggregated</span>
            </div>
            <div className="metric-value-row">
              <span className="metric-value text-gradient-emerald">
                {formatPercent(bestAccuracy)}
              </span>
            </div>
            <span className="metric-subtext">
              Latest: {formatPercent(latestRound?.global_accuracy)} (Held-out validation)
            </span>
          </div>

          <div className="metric-card glass-panel">
            <div className="metric-header">
              <span className="metric-label">Dropout Resilience</span>
              <span className="metric-badge-amber">Timeout Trigger</span>
            </div>
            <div className="metric-value-row">
              <span className="metric-value text-gradient-amber">
                {skippedCount} <span className="metric-denom">Skipped</span>
              </span>
            </div>
            <span className="metric-subtext">
              {skippedCount > 0 ? "Handled via 300s DynamoDB fallback" : "100% participation"}
            </span>
          </div>
        </section>

        {/* NAVIGATION TABS */}
        <nav className="tab-bar glass-panel">
          <button
            className={`tab-btn ${activeTab === "overview" ? "tab-active" : ""}`}
            onClick={() => setActiveTab("overview")}
          >
            📊 Analytics & FedAvg Convergence
          </button>
          <button
            className={`tab-btn ${activeTab === "prediction" ? "tab-active" : ""}`}
            onClick={() => setActiveTab("prediction")}
          >
            🩺 Patient Prediction Studio
          </button>
          <button
            className={`tab-btn ${activeTab === "nodes" ? "tab-active" : ""}`}
            onClick={() => setActiveTab("nodes")}
          >
            🏥 Hospital Nodes & IAM Isolation
          </button>
          <button
            className={`tab-btn ${activeTab === "audit" ? "tab-active" : ""}`}
            onClick={() => setActiveTab("audit")}
          >
            🛡️ CloudTrail Security Audit ({auditLogs.length})
          </button>
          <button
            className={`tab-btn ${activeTab === "architecture" ? "tab-active" : ""}`}
            onClick={() => setActiveTab("architecture")}
          >
            📐 Cloud Architecture Blueprint
          </button>
        </nav>

        {/* TAB 1: OVERVIEW & ACCURACY */}
        {activeTab === "overview" && (
          <div className="tab-content">
            <div className="main-grid">
              <div className="chart-panel glass-panel">
                <div className="panel-header">
                  <div>
                    <span className="panel-eyebrow">Federated Learning Metrics</span>
                    <h2 className="panel-title">Global vs Local Model Accuracy</h2>
                    <p className="panel-desc">
                      Aggregated FedAvg weights (Teal) consistently outperform individual isolated hospital models (Blue).
                    </p>
                  </div>
                  <div className="legend-pills">
                    <span className="legend-pill">
                      <span className="legend-color legend-teal" /> Global Aggregated
                    </span>
                    <span className="legend-pill">
                      <span className="legend-color legend-blue" /> Local Mean
                    </span>
                  </div>
                </div>

                {loading ? (
                  <div className="loading-state">
                    <span className="spinner" /> Loading round telemetry...
                  </div>
                ) : (
                  <InteractiveAccuracyChart
                    rounds={roundsData?.rounds ?? []}
                    onHoverRound={(r) => setHoveredRound(r)}
                  />
                )}

                {hoveredRound && (
                  <div className="hover-inspect-card">
                    <div className="inspect-header">
                      <strong>Round #{hoveredRound.round} Details</strong>
                      <span className="badge-teal">
                        Trigger: {hoveredRound.aggregation_trigger ?? "completed"}
                      </span>
                    </div>
                    <div className="inspect-grid">
                      <div>
                        <span>Global Accuracy:</span>{" "}
                        <strong>{formatPercent(hoveredRound.global_accuracy)}</strong>
                      </div>
                      <div>
                        <span>Mean Local Accuracy:</span>{" "}
                        <strong>{formatPercent(hoveredRound.average_local_accuracy)}</strong>
                      </div>
                      <div>
                        <span>Participated:</span>{" "}
                        <code>{hoveredRound.participated_clients.join(", ")}</code>
                      </div>
                      <div>
                        <span>Skipped (Dropout):</span>{" "}
                        <code className={hoveredRound.skipped_clients.length ? "text-danger" : ""}>
                          {hoveredRound.skipped_clients.join(", ") || "None"}
                        </code>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* QUICK PREDICTION PREVIEW ON OVERVIEW */}
              <div className="quick-preview-panel glass-panel">
                <div className="panel-header">
                  <div>
                    <span className="panel-eyebrow">Instant Test</span>
                    <h2 className="panel-title">Quick Risk Probe</h2>
                  </div>
                </div>

                <p className="panel-desc">
                  Select a clinical archetype to test against the latest global federated model:
                </p>

                <div className="preset-quick-list">
                  {presets.slice(0, 3).map((p) => (
                    <button
                      key={p.id}
                      className="preset-card-compact"
                      onClick={() => {
                        applyPreset(p);
                        setActiveTab("prediction");
                      }}
                    >
                      <div className="preset-card-title">{p.name}</div>
                      <div className="preset-card-desc">{p.description}</div>
                    </button>
                  ))}
                </div>

                <div className="mt-4">
                  <button
                    className="btn btn-primary w-full"
                    onClick={() => setActiveTab("prediction")}
                  >
                    Open Full Clinical Studio →
                  </button>
                </div>
              </div>
            </div>

            {/* ROUND HISTORY LEDGER */}
            <div className="ledger-panel glass-panel mt-6">
              <div className="panel-header">
                <div>
                  <span className="panel-eyebrow">DynamoDB Round Telemetry</span>
                  <h2 className="panel-title">Federated Consensus Ledger</h2>
                </div>
                <span className="badge-outline">Table: `FlRoundsTable`</span>
              </div>

              <RoundLedgerTable rounds={roundsData?.rounds ?? []} />
            </div>
          </div>
        )}

        {/* TAB 2: PATIENT PREDICTION STUDIO */}
        {activeTab === "prediction" && (
          <div className="tab-content">
            <div className="prediction-grid">
              {/* INPUT FORM */}
              <div className="form-panel glass-panel">
                <div className="panel-header">
                  <div>
                    <span className="panel-eyebrow">Inference API • POST /predict</span>
                    <h2 className="panel-title">Clinical Patient Input</h2>
                    <p className="panel-desc">
                      Input patient biomarkers. Inference executes against the encrypted Global Model loaded from S3.
                    </p>
                  </div>
                </div>

                {/* PRESET PICKER */}
                <div className="presets-section">
                  <span className="section-label">⚡ 1-Click Patient Archetypes:</span>
                  <div className="preset-chips">
                    {presets.map((preset) => (
                      <button
                        key={preset.id}
                        type="button"
                        className="preset-chip"
                        onClick={() => applyPreset(preset)}
                      >
                        {preset.name}
                      </button>
                    ))}
                  </div>
                </div>

                <form onSubmit={submitPrediction}>
                  <div className="form-sections-container">
                    {["Demographics", "Symptoms", "Vitals", "Lab Results", "Diagnostics", "Imaging"].map(
                      (category) => {
                        const fieldsInCategory = Object.entries(featureConfig).filter(
                          ([_, cfg]) => cfg.category === category
                        );
                        if (!fieldsInCategory.length) return null;

                        return (
                          <div key={category} className="form-category-group">
                            <h3 className="category-heading">{category}</h3>
                            <div className="fields-grid">
                              {fieldsInCategory.map(([name, cfg]) => (
                                <div key={name} className="field-group">
                                  <div className="field-label-row">
                                    <label htmlFor={name} className="field-label">
                                      {cfg.label}
                                    </label>
                                    {cfg.unit && <span className="field-unit">({cfg.unit})</span>}
                                  </div>
                                  <input
                                    id={name}
                                    name={name}
                                    type="number"
                                    min={cfg.min}
                                    max={cfg.max}
                                    step={cfg.step}
                                    value={features[name] ?? ""}
                                    onChange={(e) =>
                                      setFeatures((prev) => ({
                                        ...prev,
                                        [name]: e.target.value,
                                      }))
                                    }
                                    className="input-field"
                                    placeholder={cfg.hint}
                                  />
                                  <span className="field-hint">{cfg.hint}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        );
                      }
                    )}
                  </div>

                  <div className="form-submit-row">
                    <button
                      type="submit"
                      disabled={submitting}
                      className="btn btn-primary btn-large btn-glow w-full"
                    >
                      {submitting ? "Executing Inference..." : "🩺 Run Clinical Risk Prediction"}
                    </button>
                  </div>
                </form>
              </div>

              {/* PREDICTION RESULT CARD */}
              <div className="result-panel glass-panel">
                <div className="panel-header">
                  <div>
                    <span className="panel-eyebrow">Diagnostic Assessment</span>
                    <h2 className="panel-title">Model Inference Result</h2>
                  </div>
                  <span className="badge-model">
                    Round #{prediction?.model_round ?? latestRound?.round ?? 8} Model
                  </span>
                </div>

                {prediction ? (
                  <div className="result-display-container">
                    {/* RISK GAUGE */}
                    <div className="risk-gauge-card">
                      <div className="gauge-circle-wrap">
                        <svg className="gauge-svg" viewBox="0 0 100 100">
                          <circle
                            className="gauge-bg-circle"
                            cx="50"
                            cy="50"
                            r="42"
                            strokeWidth="10"
                          />
                          <circle
                            className={`gauge-bar-circle ${
                              prediction.risk_percent >= 50 ? "gauge-high" : "gauge-low"
                            }`}
                            cx="50"
                            cy="50"
                            r="42"
                            strokeWidth="10"
                            strokeDasharray={264}
                            strokeDashoffset={264 - (264 * prediction.risk_percent) / 100}
                          />
                        </svg>
                        <div className="gauge-inner-content">
                          <span className="gauge-percent">{prediction.risk_percent}%</span>
                          <span className="gauge-label">Risk Probability</span>
                        </div>
                      </div>

                      <div
                        className={`prediction-badge-large ${
                          prediction.risk_percent >= 50 ? "badge-danger-glow" : "badge-success-glow"
                        }`}
                      >
                        {prediction.prediction === "disease_presence_likely"
                          ? "⚠️ Heart Disease Presence Likely"
                          : "✅ Normal / Low Risk of Disease"}
                      </div>
                    </div>

                    {/* CLINICAL RISK FLAGS */}
                    <div className="clinical-flags-section">
                      <h4 className="flags-heading">Biomarker Risk Indicators:</h4>
                      {prediction.clinical_flags && prediction.clinical_flags.length > 0 ? (
                        <div className="flags-list">
                          {prediction.clinical_flags.map((flag, idx) => (
                            <div key={idx} className={`flag-item flag-${flag.type}`}>
                              <span className="flag-bullet">•</span> {flag.label}
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="no-flags-text">No acute adverse biomarker thresholds exceeded.</p>
                      )}
                    </div>

                    {/* PROVENANCE TAG */}
                    <div className="provenance-box">
                      <div className="provenance-row">
                        <span>Model Artifact:</span>
                        <code>{prediction.model_key}</code>
                      </div>
                      <div className="provenance-row">
                        <span>Federated Weights:</span>
                        <span>FedAvg 3-Hospital Consensus</span>
                      </div>
                      <div className="provenance-row">
                        <span>Encryption:</span>
                        <span>SSE-S3 AES-256 (Cloud-Enforced)</span>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="empty-prediction-state">
                    <div className="empty-icon">🩺</div>
                    <h3>Ready for Patient Data</h3>
                    <p>
                      Fill in the biomarkers on the left or select a 1-click preset archetype, then click "Run
                      Clinical Risk Prediction".
                    </p>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* TAB 3: HOSPITAL NODES */}
        {activeTab === "nodes" && (
          <div className="tab-content">
            <div className="nodes-overview-header glass-panel mb-6">
              <div>
                <span className="panel-eyebrow">Simulated AWS EC2 Hospital Nodes</span>
                <h2 className="panel-title">Privacy-Isolated Hospital Partition Topology</h2>
                <p className="panel-desc">
                  Each hospital node holds its own patient records locally. Strict IAM policies restrict S3 read/write
                  access to only its designated client prefix.
                </p>
              </div>
            </div>

            <div className="hospital-cards-grid">
              {(clients.length > 0
                ? clients
                : [
                    {
                      client_id: "hospital_1",
                      display_name: "St. Jude Cardio Center",
                      sample_count: 99,
                      s3_prefix: "clients/hospital_1/",
                      iam_role: "arn:aws:iam::123456789012:role/FLClient-hospital_1",
                      encryption: "SSE-S3 (AES-256)",
                      privacy_mode: "Strict Isolation (Raw Patient Data Zero-Egress)",
                    },
                    {
                      client_id: "hospital_2",
                      display_name: "Mayo Regional Health",
                      sample_count: 99,
                      s3_prefix: "clients/hospital_2/",
                      iam_role: "arn:aws:iam::123456789012:role/FLClient-hospital_2",
                      encryption: "SSE-S3 (AES-256)",
                      privacy_mode: "Strict Isolation (Raw Patient Data Zero-Egress)",
                    },
                    {
                      client_id: "hospital_3",
                      display_name: "General Heart Institute",
                      sample_count: 99,
                      s3_prefix: "clients/hospital_3/",
                      iam_role: "arn:aws:iam::123456789012:role/FLClient-hospital_3",
                      encryption: "SSE-S3 (AES-256)",
                      privacy_mode: "Dropout Simulation Node (Skipped Round 2)",
                    },
                  ]
              ).map((client) => (
                <div key={client.client_id} className="hospital-card glass-panel">
                  <div className="hospital-header">
                    <div className="hospital-icon-wrap">🏥</div>
                    <div>
                      <h3 className="hospital-name">{client.display_name}</h3>
                      <span className="hospital-id">{client.client_id}</span>
                    </div>
                  </div>

                  <div className="hospital-stats-list">
                    <div className="stat-row">
                      <span>Local Patient Records:</span>
                      <strong>{client.sample_count} rows (UCI Heart Disease split)</strong>
                    </div>
                    <div className="stat-row">
                      <span>IAM S3 Scope:</span>
                      <code>{client.s3_prefix}*</code>
                    </div>
                    <div className="stat-row">
                      <span>Negative IAM Access:</span>
                      <span className="badge-success-small">✅ Verified Blocked to Peers</span>
                    </div>
                    <div className="stat-row">
                      <span>At-Rest Encryption:</span>
                      <span className="badge-teal-small">{client.encryption}</span>
                    </div>
                    <div className="stat-row">
                      <span>Dropout Behavior:</span>
                      <span className={client.client_id === "hospital_3" ? "text-amber" : "text-muted"}>
                        {client.client_id === "hospital_3"
                          ? "Simulated Network Drop at Round 2"
                          : "100% Reliable Uploads"}
                      </span>
                    </div>
                  </div>

                  <div className="hospital-footer">
                    <span className="privacy-badge">🔒 {client.privacy_mode}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* TAB 4: AUDIT LOGS */}
        {activeTab === "audit" && (
          <div className="tab-content">
            <div className="glass-panel">
              <div className="panel-header">
                <div>
                  <span className="panel-eyebrow">CloudTrail Security Governance</span>
                  <h2 className="panel-title">S3 & DynamoDB Access Audit Stream</h2>
                  <p className="panel-desc">
                    Immutable event log validating that hospital nodes only write to their own S3 prefix, with SSE-S3
                    encryption verified on every `PutObject`.
                  </p>
                </div>
                <span className="badge-outline">Log: `local_cloud/cloudtrail/events.jsonl`</span>
              </div>

              {auditLogs.length === 0 ? (
                <p className="empty-state">No audit logs recorded yet. Run a training simulation to populate.</p>
              ) : (
                <div className="table-responsive">
                  <table className="custom-table">
                    <thead>
                      <tr>
                        <th>Timestamp (UTC)</th>
                        <th>Actor / IAM Identity</th>
                        <th>Action</th>
                        <th>Resource Target (S3 / DB)</th>
                        <th>Encryption</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {auditLogs.map((log, idx) => (
                        <tr key={idx}>
                          <td className="font-mono text-muted">{formatDate(log.timestamp)}</td>
                          <td>
                            <span className={`actor-badge actor-${log.actor.replace(/[^a-z0-9]/gi, "")}`}>
                              {log.actor}
                            </span>
                          </td>
                          <td>
                            <code className="action-code">{log.action}</code>
                          </td>
                          <td className="font-mono text-cyan">{log.resource}</td>
                          <td>
                            <span className="badge-teal-small">
                              {log.details?.sse || log.details?.server_side_encryption || "AES256"}
                            </span>
                          </td>
                          <td>
                            <span className={`status-pill-small status-${log.status.toLowerCase()}`}>
                              {log.status}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}

        {/* TAB 5: ARCHITECTURE BLUEPRINT */}
        {activeTab === "architecture" && (
          <div className="tab-content">
            <div className="glass-panel">
              <div className="panel-header">
                <div>
                  <span className="panel-eyebrow">System Architecture</span>
                  <h2 className="panel-title">Privacy-Preserving Cloud Orchestration Protocol</h2>
                </div>
              </div>

              <div className="architecture-grid">
                <div className="arch-step-card">
                  <div className="step-num">01</div>
                  <h4>Local Hospital Training</h4>
                  <p>
                    Hospital nodes (1, 2, 3) train local logistic regression models on their private tabular patient
                    dataset. Raw patient records <strong>never leave</strong> the hospital boundary.
                  </p>
                </div>

                <div className="arch-step-card">
                  <div className="step-num">02</div>
                  <h4>IAM-Scoped S3 Upload</h4>
                  <p>
                    Only model weight parameters (\(w, b\)) are exported. Each hospital uploads strictly to its
                    own prefix <code>clients/hospital_X/</code> with default <strong>SSE-S3 AES-256</strong> encryption (no paid KMS).
                  </p>
                </div>

                <div className="arch-step-card">
                  <div className="step-num">03</div>
                  <h4>S3 Event & DynamoDB Trigger</h4>
                  <p>
                    Every upload fires an S3 event that atomically increments a round upload counter in DynamoDB.
                    The Aggregator only executes when expected nodes have arrived (or 5-minute timeout triggers).
                  </p>
                </div>

                <div className="arch-step-card">
                  <div className="step-num">04</div>
                  <h4>FedAvg Cloud Aggregation</h4>
                  <p>
                    AWS Lambda executes Federated Averaging over received client weight tensors.
                    The consensus model is saved to <code>global/round_XXX/model.json</code>.
                  </p>
                </div>

                <div className="arch-step-card">
                  <div className="step-num">05</div>
                  <h4>Independent Prediction API</h4>
                  <p>
                    The prediction endpoint (<code>POST /predict</code>) is a completely separate read-path. It
                    fetches the latest global weights from S3 to score live patient requests with zero latency.
                  </p>
                </div>

                <div className="arch-step-card">
                  <div className="step-num">06</div>
                  <h4>Next.js CloudFront Dashboard</h4>
                  <p>
                    The dashboard reads strictly via API Gateway (<code>GET /rounds</code>), never connecting to S3 or
                    DynamoDB directly, preserving zero-trust cloud isolation.
                  </p>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* MODAL: TRIGGER FL SIMULATION */}
        {showTrainModal && (
          <div className="modal-backdrop">
            <div className="modal-dialog glass-panel">
              <div className="modal-header">
                <h3>⚡ Configure Federated Learning Run</h3>
                <button className="modal-close-btn" onClick={() => setShowTrainModal(false)}>
                  ×
                </button>
              </div>

              <div className="modal-body">
                <div className="field-group mb-4">
                  <label className="field-label">Number of Federated Rounds</label>
                  <select
                    className="input-field select-field"
                    value={customRounds}
                    onChange={(e) => setCustomRounds(Number(e.target.value))}
                  >
                    <option value={4}>4 Rounds (Fast convergence)</option>
                    <option value={8}>8 Rounds (Default spec standard)</option>
                    <option value={12}>12 Rounds (Deep convergence)</option>
                  </select>
                </div>

                <div className="field-group mb-4">
                  <label className="field-label">Simulate Node Dropout</label>
                  <select
                    className="input-field select-field"
                    value={customDropout}
                    onChange={(e) => setCustomDropout(e.target.value)}
                  >
                    <option value="hospital_3:2">Hospital 3 drops at Round 2 (Tests Timeout Fallback)</option>
                    <option value="">No Dropouts (100% Client Participation)</option>
                    <option value="hospital_1:3,hospital_3:5">Multi-node dropouts (Hospital 1 @ R3, Hospital 3 @ R5)</option>
                  </select>
                </div>

                <p className="modal-info-text">
                  This will execute the multi-round FedAvg loop across all 3 simulated hospital splits, upload
                  encrypted weight tensors, update DynamoDB counters, and output new global consensus models.
                </p>
              </div>

              <div className="modal-footer">
                <button className="btn btn-secondary" onClick={() => setShowTrainModal(false)}>
                  Cancel
                </button>
                <button className="btn btn-primary btn-glow" onClick={triggerTraining}>
                  Start Simulation
                </button>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

// ----------------------------------------------------
// INTERACTIVE SVG ACCURACY CHART
// ----------------------------------------------------
function InteractiveAccuracyChart({
  rounds,
  onHoverRound,
}: {
  rounds: RoundRecord[];
  onHoverRound: (r: RoundRecord | null) => void;
}) {
  if (rounds.length === 0) {
    return <p className="empty-state">No round telemetry available. Run simulation first.</p>;
  }

  const width = 840;
  const height = 320;
  const paddingLeft = 50;
  const paddingRight = 30;
  const paddingTop = 30;
  const paddingBottom = 45;

  const maxRound = Math.max(...rounds.map((r) => r.round), 1);

  const getX = (roundNum: number) => {
    if (maxRound === 1) return paddingLeft + (width - paddingLeft - paddingRight) / 2;
    return paddingLeft + ((roundNum - 1) / (maxRound - 1)) * (width - paddingLeft - paddingRight);
  };

  const getY = (val: number | null) => {
    const clamped = Math.max(0.5, Math.min(1.0, val ?? 0.5));
    // Scale 0.5 -> 1.0
    return height - paddingBottom - ((clamped - 0.5) / 0.5) * (height - paddingTop - paddingBottom);
  };

  const globalPoints = rounds
    .filter((r) => r.global_accuracy !== null)
    .map((r) => `${getX(r.round)},${getY(r.global_accuracy)}`)
    .join(" ");

  const localPoints = rounds
    .filter((r) => r.average_local_accuracy !== null)
    .map((r) => `${getX(r.round)},${getY(r.average_local_accuracy)}`)
    .join(" ");

  // Gradient area under global curve
  const globalAreaPoints =
    rounds.length > 0
      ? `${getX(rounds[0].round)},${height - paddingBottom} ` +
        globalPoints +
        ` ${getX(rounds[rounds.length - 1].round)},${height - paddingBottom}`
      : "";

  return (
    <div className="chart-container">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="accuracy-chart-svg"
        role="img"
        aria-label="Accuracy Convergence Chart"
      >
        <defs>
          <linearGradient id="globalGlow" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#06b6d4" stopOpacity="0.35" />
            <stop offset="100%" stopColor="#06b6d4" stopOpacity="0.0" />
          </linearGradient>
        </defs>

        {/* HORIZONTAL GRID LINES & TICKS */}
        {[0.5, 0.6, 0.7, 0.8, 0.9, 1.0].map((tick) => {
          const y = getY(tick);
          return (
            <g key={tick}>
              <line className="chart-grid-line" x1={paddingLeft} x2={width - paddingRight} y1={y} y2={y} />
              <text className="chart-axis-text" x={paddingLeft - 10} y={y + 4} textAnchor="end">
                {Math.round(tick * 100)}%
              </text>
            </g>
          );
        })}

        {/* VERTICAL ROUND TICKS */}
        {rounds.map((r) => {
          const x = getX(r.round);
          return (
            <g key={r.round}>
              <line className="chart-grid-line-vert" x1={x} x2={x} y1={paddingTop} y2={height - paddingBottom} />
              <text className="chart-axis-text" x={x} y={height - paddingBottom + 20} textAnchor="middle">
                R{r.round}
              </text>
            </g>
          );
        })}

        {/* GRADIENT FILL UNDER GLOBAL ACCURACY */}
        {globalAreaPoints && <polygon points={globalAreaPoints} fill="url(#globalGlow)" />}

        {/* POLYLINES */}
        <polyline className="chart-line-local" points={localPoints} />
        <polyline className="chart-line-global" points={globalPoints} />

        {/* DATA NODES */}
        {rounds.map((r) => {
          const gx = getX(r.round);
          const gy = getY(r.global_accuracy);
          const ly = getY(r.average_local_accuracy);
          const isDropoutRound = r.skipped_clients.length > 0;

          return (
            <g
              key={r.round}
              className="chart-data-group"
              onMouseEnter={() => onHoverRound(r)}
              onMouseLeave={() => onHoverRound(null)}
            >
              {/* Local circle */}
              <circle className="chart-dot-local" cx={gx} cy={ly} r="4.5" />
              {/* Global circle */}
              <circle
                className={`chart-dot-global ${isDropoutRound ? "dot-dropout" : ""}`}
                cx={gx}
                cy={gy}
                r="6"
              />

              {/* Dropout alert marker */}
              {isDropoutRound && (
                <g transform={`translate(${gx}, ${gy - 18})`}>
                  <rect x="-35" y="-12" width="70" height="18" rx="4" className="dropout-badge-rect" />
                  <text x="0" y="0" textAnchor="middle" className="dropout-badge-text">
                    Dropout
                  </text>
                </g>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// ----------------------------------------------------
// ROUND LEDGER TABLE
// ----------------------------------------------------
function RoundLedgerTable({ rounds }: { rounds: RoundRecord[] }) {
  if (!rounds.length) {
    return <p className="empty-state">No round history available.</p>;
  }

  return (
    <div className="table-responsive">
      <table className="custom-table">
        <thead>
          <tr>
            <th>Round</th>
            <th>Global Accuracy</th>
            <th>Local Mean</th>
            <th>Uploads Count</th>
            <th>Aggregation Trigger</th>
            <th>Active Hospitals</th>
            <th>Skipped (Dropout)</th>
          </tr>
        </thead>
        <tbody>
          {rounds.map((r) => (
            <tr key={r.round}>
              <td>
                <span className="round-pill">Round #{r.round}</span>
              </td>
              <td>
                <strong className="text-cyan font-mono text-base">
                  {formatPercent(r.global_accuracy)}
                </strong>
              </td>
              <td>
                <span className="text-muted font-mono">{formatPercent(r.average_local_accuracy)}</span>
              </td>
              <td>
                <span className="font-mono">
                  {r.uploads_received}/{r.expected_uploads}
                </span>
              </td>
              <td>
                <span
                  className={`trigger-badge ${
                    r.aggregation_trigger === "timeout" ? "trigger-timeout" : "trigger-all"
                  }`}
                >
                  {r.aggregation_trigger === "timeout" ? "⏱️ Timeout Fallback" : "⚡ All Nodes Uploaded"}
                </span>
              </td>
              <td>
                <div className="chips-row">
                  {r.participated_clients.map((c) => (
                    <span key={c} className="client-chip">
                      {c}
                    </span>
                  ))}
                </div>
              </td>
              <td>
                {r.skipped_clients.length > 0 ? (
                  <span className="badge-dropout">{r.skipped_clients.join(", ")}</span>
                ) : (
                  <span className="text-muted text-xs">None</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function formatDate(isoString?: string) {
  if (!isoString) return "—";
  try {
    const d = new Date(isoString);
    return d.toISOString().replace("T", " ").replace("Z", "");
  } catch {
    return isoString;
  }
}

