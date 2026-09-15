/** Mirrors the FastAPI response models in backend/app/schemas. */

export interface CorpusStats {
  minutes_collected: number;
  hours_collected: number;
  posts_scanned: number;
  matches_stored: number;
  alerts: number;
  terms_tracked: number;
  samples_stored: number;
  trends_tracked: number;
  events_found: number;
  first_minute: number | null;
  last_minute: number | null;
  collecting: boolean;
  /** How far the processed stream trails wall-clock. */
  lag_seconds: number | null;
  /** True once the earliest horizon (fast, one hour) can score. */
  ready_for_detection: boolean;
  /** Minutes until the earliest horizon is ready. */
  minutes_needed: number;
  horizons: HorizonStatus[];
}

/**
 * One detection horizon. Warm-up is (window + gap + 1) * bucket_minutes, so
 * the bucket size alone decides how soon this horizon can say anything.
 */
export interface HorizonStatus {
  mode: string;
  description: string;
  bucket_minutes: number;
  baseline_window: number;
  z_threshold: number;
  min_hits: number;
  warmup_minutes: number;
  warmup_hours: number;
  ready: boolean;
  minutes_remaining: number;
  alerts: number;
}

export interface TopicSummary {
  name: string;
  phrases: string[];
  /** Empty means the topic matches any language. */
  langs: string[];
  total_hits: number;
}

export interface SeriesPoint {
  t: number;
  hits: number;
  total: number;
  share: number;
  coverage: number;
}

export interface TopicSeries {
  topic: string;
  bucket_minutes: number;
  points: SeriesPoint[];
}

export interface Alert {
  id: number;
  /** The topic name or discovered term that spiked. */
  subject: string;
  /** "topic" (declared in topics.json) or "term" (found in the stream). */
  kind: string;
  /** The horizon that raised this alert: fast, mid or deep. */
  mode: string;
  bucket: number;
  hits: number;
  total: number;
  share: number;
  baseline: number;
  zscore: number;
  multiple: number;
  terms: string[];
  /** Most-shared URLs inside the spike. Usually the story itself. */
  links: string[];
  /**
   * Learned probability the spike holds rather than reverting. Null until a
   * model has been fitted, which is the normal state early on.
   */
  confidence: number | null;
  created_at: number;
}

export interface Post {
  ts: number;
  did: string;
  rkey: string;
  lang: string | null;
  text: string;
  url: string;
}

export interface DetectionRun {
  ran: boolean;
  mode: string;
  kind: string;
  reason: string | null;
  alerts_found: number;
  new_alerts: number;
  topics_scanned: number;
  bucket_minutes: number;
  z_threshold: number;
  minutes_remaining: number;
}

/** One Bluesky trend, and the alert that found it first - if any did. */
export interface TrendMatch {
  topic: string;
  display_name: string;
  category: string;
  status: string;
  post_count: number;
  first_seen: number;
  matched: boolean;
  match_basis: string;
  alert_id: number | null;
  alert_subject: string | null;
  alert_kind: string | null;
  alert_mode: string | null;
  alert_bucket: number | null;
  /** Positive means sky-pulse raised it before Bluesky listed it. */
  lead_minutes: number | null;
}

export interface BenchmarkReport {
  trends_tracked: number;
  events_found: number;
  matched: number;
  coverage: number;
  median_lead_minutes: number | null;
  best_lead_minutes: number | null;
  rows: TrendMatch[];
}

/** The fitted confidence model, or null when none exists yet. */
export interface ModelInfo {
  feature_names: string[];
  weights: number[];
  bias: number;
  trained_on: number;
  positives: number;
  accuracy: number;
  auc: number;
  holdout_auc: number | null;
  holdout_size: number;
  label: string;
  top_factors: [string, number][];
}

/** A story: terms that spiked together, chained across windows. */
export interface PulseEvent {
  key: string;
  mode: string;
  terms: string[];
  first_bucket: number;
  last_bucket: number;
  buckets: number;
  hits: number;
  zscore: number;
  confidence: number | null;
  links: string[];
  story_did: string | null;
  story_rkey: string | null;
  story_ts: number | null;
  story_text: string | null;
  /** 1.0 means nothing like it had been said before. */
  story_novelty: number | null;
  story_url: string | null;
  /** Similarity to the closest earlier event. */
  recurrence: number | null;
  /** Key of the earlier event this repeats, when it does. */
  recurs_from: string | null;
}
