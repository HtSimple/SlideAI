export type ComplexityTier = "fast" | "balanced" | "advanced";
export type TaskStatus =
  | "DRAFT"
  | "FILES_PROCESSING"
  | "READY"
  | "WAITING_REQUIREMENT_INPUT"
  | "WAITING_OUTLINE_CONFIRMATION"
  | "RUNNING"
  | "WAITING_USER_FEEDBACK"
  | "FAILED_RETRYABLE"
  | "FAILED_FINAL"
  | "CANCELLED"
  | "COMPLETED";

export interface ModelPreference {
  mode: "auto" | "manual";
  model_key?: string | null;
}

export interface RawRequirement {
  topic: string;
  target_page_count: number;
  scenario?: string;
  audience?: string;
  style?: string;
  special_constraints?: string[];
  estimated_reference_tokens?: number;
}

export interface TaskRecord {
  id: string;
  name: string;
  status: TaskStatus;
  current_stage: string | null;
  raw_requirement: RawRequirement;
  model_preference: ModelPreference;
  complexity: {
    tier: ComplexityTier;
    total_score: number;
    factors: Record<string, number>;
  };
  version: number;
  created_at: string;
  updated_at: string;
}

export interface TaskPage {
  items: TaskRecord[];
  total: number;
  offset: number;
  limit: number;
  status_counts: Record<string, number>;
}

export interface ModelOption {
  key: string;
  display_name: string;
  tier: ComplexityTier;
  enabled: boolean;
  available: boolean;
}

export interface CreateTaskInput {
  raw_requirement: RawRequirement;
  model_preference: ModelPreference;
}
