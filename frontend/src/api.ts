import type {
  CVProfile,
  DeleteResult,
  Health,
  Job,
  JobDetail,
  JobList,
  Run,
  Settings,
  SourceInfo,
  Stats,
  Status,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: init?.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...init,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* keep the status text */
    }
    throw new ApiError(detail, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export interface TrackingUpdate {
  status?: Status;
  notes?: string;
  contact?: string;
  applied_date?: string | null;
  follow_up_date?: string | null;
  /** A free-text timeline entry. */
  log?: string;
}

export interface JobQuery {
  status?: Status[];
  source?: string[];
  min_score?: number;
  remote_only?: boolean;
  english_only?: boolean;
  search?: string;
  follow_up_due?: boolean;
  sort?: string;
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
}

function toQueryString(query: JobQuery): string {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    if (Array.isArray(value)) {
      value.forEach((item) => params.append(key, String(item)));
    } else {
      params.set(key, String(value));
    }
  });
  return params.toString();
}

export const api = {
  health: () => request<Health>("/api/health"),
  stats: () => request<Stats>("/api/stats"),

  jobs: (query: JobQuery = {}) => request<JobList>(`/api/jobs?${toQueryString(query)}`),
  job: (id: number) => request<JobDetail>(`/api/jobs/${id}`),
  /** Partial update: only the keys present are changed; `null` clears a date. */
  track: (id: number, payload: TrackingUpdate) =>
    request<Job["application"]>(`/api/jobs/${id}/status`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  setStatus: (id: number, status: Status) =>
    request<Job["application"]>(`/api/jobs/${id}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
  deleteEvent: (jobId: number, eventId: number) =>
    request<void>(`/api/jobs/${jobId}/events/${eventId}`, { method: "DELETE" }),
  rescore: (id: number) => request<JobDetail>(`/api/jobs/${id}/rescore`, { method: "POST" }),
  deleteJob: (id: number) => request<void>(`/api/jobs/${id}`, { method: "DELETE" }),
  deleteAllJobs: () => request<DeleteResult>("/api/jobs?confirm=true", { method: "DELETE" }),

  settings: () => request<Settings>("/api/settings"),
  saveSettings: (settings: Settings) =>
    request<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(settings) }),
  sources: () => request<SourceInfo[]>("/api/settings/sources"),

  runs: () => request<Run[]>("/api/runs"),
  triggerRun: () => request<{ status: string }>("/api/runs", { method: "POST" }),
  runActive: () => request<{ active: boolean }>("/api/runs/active"),
  deleteRun: (id: number) => request<DeleteResult>(`/api/runs/${id}`, { method: "DELETE" }),
  deleteAllRuns: () => request<DeleteResult>("/api/runs?confirm=true", { method: "DELETE" }),

  cv: () => request<CVProfile | null>("/api/cv"),
  cvRaw: () => request<{ filename: string; text: string }>("/api/cv/raw"),
  uploadCV: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<CVProfile>("/api/cv/upload", { method: "POST", body: form });
  },
  uploadCVText: (text: string, filename = "pasted-cv.txt") =>
    request<CVProfile>("/api/cv/text", {
      method: "POST",
      body: JSON.stringify({ text, filename }),
    }),
};
