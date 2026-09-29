export type Status =
  | "new"
  | "applied"
  | "system_rejected"
  | "rejected"
  | "interested"
  | "ignored";

/** In the order the user thinks about them. */
export const STATUSES: Status[] = [
  "new",
  "applied",
  "system_rejected",
  "rejected",
  "interested",
  "ignored",
];

export const STATUS_LABELS: Record<Status, string> = {
  new: "New",
  applied: "Applied",
  system_rejected: "Rejected by system",
  rejected: "Rejected",
  interested: "Interested",
  ignored: "Ignored",
};

export interface Analysis {
  similarity: number | null;
  score: number | null;
  matched: string[];
  missing: string[];
  verdict: string;
  working_language: string | null;
  german_required: boolean | null;
  language_confidence: number | null;
  detected_language: string | null;
  language_evidence: string;
  stage: string;
  error: string | null;
  analyzed_at: string | null;
}

export interface ApplicationInfo {
  status: Status;
  applied_date: string | null;
  follow_up_date: string | null;
  contact: string;
  notes: string;
  status_changed_at: string | null;
  updated_at: string | null;
}

export interface TimelineEvent {
  id: number;
  created_at: string;
  actor: "user" | "system" | string;
  from_status: Status | null;
  to_status: Status | null;
  note: string;
}

export interface Job {
  id: number;
  external_id: string;
  source: string;
  /** The board behind an aggregated result, e.g. Indeed or StepStone. */
  publisher: string;
  title: string;
  company: string;
  location: string;
  remote: boolean;
  url: string;
  posted_date: string | null;
  first_seen: string;
  analysis: Analysis | null;
  application: ApplicationInfo;
}

export interface JobDetail extends Job {
  description: string;
  events: TimelineEvent[];
}

export interface JobList {
  total: number;
  items: Job[];
  limit: number;
  offset: number;
}

export interface ATSCompany {
  ats: string;
  slug: string;
  label: string;
  active: boolean;
}

export interface Settings {
  english_only: boolean;
  germany_only: boolean;
  min_score: number;
  auto_reject_below_min_score: boolean;
  jobs_matches_only_default: boolean;
  similarity_floor: number;
  relevance_filter: boolean;
  include_title_terms: string[];
  exclude_title_terms: string[];
  target_matches_per_run: number;
  max_llm_scores_per_run: number;
  keywords: string[];
  locations: string[];
  remote_only: boolean;
  radius_km: number;
  max_age_days: number;
  results_per_source: number;
  sources: Record<string, boolean>;
  ats_companies: ATSCompany[];
  jsearch_publishers: string[];
  jsearch_max_requests: number;
  daily_run_time: string;
  scheduler_enabled: boolean;
}

export interface SourceInfo {
  name: string;
  label: string;
  enabled: boolean;
  configured: boolean;
  requires_config: boolean;
}

export interface Run {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: string;
  trigger: string;
  fetched: number;
  new_jobs: number;
  duplicates: number;
  language_dropped: number;
  similarity_dropped: number;
  scored: number;
  passed: number;
  errors: string[];
  details: {
    per_source?: Record<string, number>;
    notes?: string[];
    duration_seconds?: number;
    llm_enabled?: boolean;
    model?: string;
    embedding_backend?: string;
    germany_dropped?: number;
    off_target?: number;
    off_target_reasons?: Record<string, number>;
    similarity_range?: number[];
  };
}

export interface Stats {
  total_jobs: number;
  by_status: Record<string, number>;
  passing: number;
  follow_ups_due: number;
  last_run: Run | null;
  llm_enabled: boolean;
  has_cv: boolean;
  min_score: number;
  matches_only_default: boolean;
}

export interface CVProfile {
  id: number;
  filename: string;
  summary: string;
  skills: string[];
  role_targets: string[];
  years_experience: number | null;
  experience: Array<Record<string, unknown>>;
  languages: string[];
  education: Array<Record<string, unknown>>;
  projects: Array<Record<string, unknown>>;
  certifications: string[];
  page_count: number | null;
  text_chars: number;
  has_embedding: boolean;
  embedding_model: string | null;
  updated_at: string;
  /** Set on upload when a stage degraded: no key, model error, embedding failure. */
  warnings?: string[];
}

export interface DeleteResult {
  deleted_jobs: number;
  deleted_runs?: number;
}

export interface Health {
  status: string;
  version: string;
  llm_enabled: boolean;
  scheduler_running: boolean;
  next_run: string | null;
}
