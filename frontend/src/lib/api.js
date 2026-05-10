import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "http://localhost:8001";
const API_BASE = `${BACKEND_URL}/api`;

const api = axios.create({
  baseURL: API_BASE,
  timeout: 180000, // 3 min — heavy LLM calls
});

export const fetchOverview     = ()           => api.get("/overview").then(r => r.data);
export const fetchHealth       = ()           => api.get("/health").then(r => r.data);
export const fetchIngestion    = ()           => api.get("/ingestion/status").then(r => r.data);
export const runIngestion      = (body)       => api.post("/ingestion/run", body).then(r => r.data);

export const analyzeAtlas      = (topic, includeAi = true) =>
  api.post("/atlas/analyze", { topic, include_ai_inferred: includeAi }).then(r => r.data);

export const verifyForensics   = (text)       =>
  api.post("/forensics/verify", { text }).then(r => r.data);

export const generateAdvocacy  = (payload)    =>
  api.post("/advocacy/generate", payload).then(r => r.data);

export const searchLive        = (query, sources, max_items = 5) =>
  api.post("/live/search", { query, sources, max_items }).then(r => r.data);

export const runCouncil        = (query, k = 6) =>
  api.post("/council/debate", { query, k }).then(r => r.data);

export const askResearch       = (query, persona = "researcher", k = 6) =>
  api.post("/research/ask", { query, persona, k }).then(r => r.data);

export const debugRetrieve     = (query, collections = "", k = 6) =>
  api.get(`/debug/retrieve`, { params: { query, collections, k } }).then(r => r.data);

// ── Tier-2 pillars ──────────────────────────────────────────────────────

export const compareDiff       = (left, right, leftLabel = "Left", rightLabel = "Right") =>
  api.post("/diff/compare", { left, right, left_label: leftLabel, right_label: rightLabel }).then(r => r.data);

export const saveReport        = (kind, title, payload) =>
  api.post("/reports", { kind, title, payload }).then(r => r.data);
export const listReports       = (kind = "") =>
  api.get("/reports", { params: kind ? { kind } : {} }).then(r => r.data);
export const getReport         = (id) =>
  api.get(`/reports/${id}`).then(r => r.data);
export const deleteReport      = (id) =>
  api.delete(`/reports/${id}`).then(r => r.data);
export const getShare          = (token) =>
  api.get(`/share/${token}`).then(r => r.data);

export const analyzeRedteam    = (text, mode = "argument") =>
  api.post("/redteam/analyze", { text, mode }).then(r => r.data);

export const trackDoctrine     = (doctrine, jurisdiction = "Comparative") =>
  api.post("/doctrine/track", { doctrine, jurisdiction }).then(r => r.data);

export const buildGraph        = (seed, maxNodes = 40) =>
  api.post("/graph/build", { seed, max_nodes: maxNodes }).then(r => r.data);

export const annotateReading   = (text) =>
  api.post("/reading/annotate", { text }).then(r => r.data);

export const voiceVerifyChunk  = (text) =>
  api.post("/voice/verify_chunk", { text }).then(r => r.data);
export const voiceFinalize     = (transcript) =>
  api.post("/voice/finalize", { transcript }).then(r => r.data);

// ── State-of-the-Art pillars (v4) ───────────────────────────────────────

export const findAdversarial   = (claim) =>
  api.post("/adversarial/find", { claim }).then(r => r.data);

export const scanArbitrage     = (scenario) =>
  api.post("/arbitrage/scan", { scenario }).then(r => r.data);

export const analyzeDrift      = (query, registries = null) =>
  api.post("/drift/analyze", { query, registries }).then(r => r.data);

export const scanSentinel      = (text, max_findings = 24) =>
  api.post("/sentinel/scan", { text, max_findings }).then(r => r.data);

export const sentinelRules     = () =>
  api.get("/sentinel/rules").then(r => r.data);

export const stressTest        = (clause) =>
  api.post("/stress/test", { clause }).then(r => r.data);

// ── Comparative IRAC (Pillar 19) ─────────────────────────────────────────

export const compareJurisdictions = (query, jurisdictions = null) =>
  api.post("/compare/analyze", { query, jurisdictions }).then(r => r.data);

export const getCompareJurisdictions = () =>
  api.get("/compare/jurisdictions").then(r => r.data);

export default api;
