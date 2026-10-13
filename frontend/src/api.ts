export type User = { id: string; email: string; role: string; created_at?: string };
export type AuthResponse = { user: User; csrf_token: string };

export type Prediction = {
  category: string;
  score_type: string;
  suggestions: { category: string; score: number }[];
  category_confident: boolean;
  needs_user_review: boolean;
  description: string;
  description_fields: Record<string, string>;
  attributes: Record<string, { eligible: boolean; reason?: string; suggestions: { value: string; score: number }[] }>;
};

export type PendingUpload = {
  id: string;
  image_url: string;
  image_sha256: string;
  width: number;
  height: number;
  quality: { warnings?: { code: string; message: string }[]; advisory_only?: boolean };
  prediction: Prediction;
  expires_at: string;
};

export type Garment = {
  id: string;
  category: string;
  garment_photo_type: "flat-lay" | "model";
  vton_eligibility: { status: string; eligible: boolean; candidate_category?: string; reason?: string; policy_version: string };
  vton_eligibility_version: string;
  color: string | null;
  pattern: string | null;
  sleeve_length: string | null;
  description: string;
  description_is_manual: boolean;
  name: string | null;
  notes: string | null;
  image_url: string;
  field_sources: Record<string, string>;
  description_provenance: Record<string, unknown>;
};

export type GarmentPage = { items: Garment[]; page: number; page_size: number; total: number };
export type PersonPhoto = { id: string; image_url: string; width: number; height: number; consent_version: string; consented_at: string; created_at: string };
export type TryOnJob = {
  id: string; state: "queued" | "running" | "succeeded" | "failed" | "timed_out" | "cancelled";
  mode: "mock" | "real"; status_url: string; result_url: string | null; error_code: string | null;
  cancellation_requested: boolean; settings_snapshot: Record<string, unknown>;
  result_metadata: Record<string, unknown> | null; created_at: string; updated_at: string; replayed?: boolean;
};
export type TryOnJobList = { items: TryOnJob[] };

const CSRF_KEY = "dressme.csrf";
export type Avatar = {
  id: string; provider: "avaturn"; provider_avatar_id: string; model_url: string;
  asset_sha256: string; asset_size: number; version: number; consent_version: string;
  created_at: string; updated_at: string;
};
export type AvatarConsent = {
  id: string; provider: "avaturn"; consent_version: string; consented_at: string;
};
let csrfToken: string | null = sessionStorage.getItem(CSRF_KEY);

export function setCsrfToken(value: string | null) {
  csrfToken = value;
  if (value) sessionStorage.setItem(CSRF_KEY, value);
  else sessionStorage.removeItem(CSRF_KEY);
}

export function getCsrfToken() {
  return csrfToken;
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (options.method && !["GET", "HEAD", "OPTIONS"].includes(options.method.toUpperCase())) {
    if (csrfToken) headers.set("X-CSRF-Token", csrfToken);
  }
  const response = await fetch(path, { ...options, headers, credentials: "include" });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const message = body?.error?.message ?? body?.detail?.message ?? `Request failed (${response.status}).`;
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const categories = ["dress", "jacket", "jeans", "shirt", "shorts", "skirt", "sweater", "sweatshirt", "t-shirt", "top", "trousers"] as const;
export const colors = ["beige", "black", "blue", "brown", "green", "grey", "navy", "orange", "pink", "purple", "red", "white", "yellow"] as const;
export const patterns = ["solid", "striped", "checked", "printed", "floral"] as const;
export const sleeves = ["sleeveless", "short", "long"] as const;
