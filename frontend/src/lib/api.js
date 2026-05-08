import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
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

export default api;
