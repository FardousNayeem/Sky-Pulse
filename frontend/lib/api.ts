/**
 * The only module that talks to the backend. Components and pages import
 * these functions; nothing else builds a URL or calls fetch.
 */
import type {
  Alert,
  BenchmarkReport,
  CorpusStats,
  DetectionRun,
  HorizonStatus,
  ModelInfo,
  Post,
  PulseEvent,
  TopicSeries,
  TopicSummary,
} from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

class ApiError extends Error {
  constructor(path: string, status: number) {
    super(`API ${path} failed with ${status}`);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, { cache: "no-store", ...init });
  if (!response.ok) throw new ApiError(path, response.status);
  return response.json() as Promise<T>;
}

/** Returns null instead of throwing, so a page can render an offline state. */
async function tryRequest<T>(path: string, init?: RequestInit): Promise<T | null> {
  try {
    return await request<T>(path, init);
  } catch {
    return null;
  }
}

export const getStats = () => tryRequest<CorpusStats>("/api/stats");

export const getTopics = () => tryRequest<TopicSummary[]>("/api/topics");

export const getAlerts = (
  limit = 100,
  subject?: string,
  mode?: string,
  kind?: string,
  sort?: string,
) =>
  tryRequest<Alert[]>(
    `/api/alerts?limit=${limit}` +
      (subject ? `&subject=${encodeURIComponent(subject)}` : "") +
      (mode ? `&mode=${encodeURIComponent(mode)}` : "") +
      (kind ? `&kind=${encodeURIComponent(kind)}` : "") +
      (sort ? `&sort=${encodeURIComponent(sort)}` : ""),
  );

export const getEvents = (limit = 50, mode?: string) =>
  tryRequest<PulseEvent[]>(
    `/api/events?limit=${limit}${mode ? `&mode=${encodeURIComponent(mode)}` : ""}`,
  );

export const getEvent = (mode: string, key: string) =>
  tryRequest<PulseEvent>(
    `/api/events/${encodeURIComponent(mode)}/${encodeURIComponent(key)}`,
  );

export const getHorizons = () => tryRequest<HorizonStatus[]>("/api/horizons");

export const getBenchmark = (limit = 100) =>
  tryRequest<BenchmarkReport>(`/api/benchmark?limit=${limit}`);

export const getModel = () =>
  tryRequest<{ model: ModelInfo | null }>("/api/model").then((r) => r?.model ?? null);

export const getSeries = (topic: string, bucketMinutes = 15, limit = 200) =>
  tryRequest<TopicSeries>(
    `/api/topics/${encodeURIComponent(topic)}/series?bucket_minutes=${bucketMinutes}&limit=${limit}`,
  );

export const getTermSeries = (term: string, bucketMinutes = 4, limit = 200) =>
  tryRequest<TopicSeries>(
    `/api/terms/${encodeURIComponent(term)}/series?bucket_minutes=${bucketMinutes}&limit=${limit}`,
  );

export const getTermPosts = (
  term: string,
  limit = 50,
  window?: { start: number; end: number },
) => {
  const range = window ? `&start=${window.start}&end=${window.end}` : "";
  return tryRequest<Post[]>(
    `/api/terms/${encodeURIComponent(term)}/posts?limit=${limit}${range}`,
  );
};

export const getPosts = (
  topic: string,
  limit = 50,
  window?: { start: number; end: number },
) => {
  const range = window ? `&start=${window.start}&end=${window.end}` : "";
  return tryRequest<Post[]>(
    `/api/topics/${encodeURIComponent(topic)}/posts?limit=${limit}${range}`,
  );
};

/**
 * Score collected history. The collector already does this on a timer, so this
 * exists for an impatient refresh, not as the only path to an alert.
 * Omit `mode` to run every horizon that is ready.
 */
export const runDetection = (mode?: string) =>
  tryRequest<DetectionRun[]>(
    `/api/detect${mode ? `?mode=${encodeURIComponent(mode)}` : ""}`,
    { method: "POST" },
  );
