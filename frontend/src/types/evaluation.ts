export interface HardCheck {
  code: string;
  passed: boolean;
  blocking: boolean;
  description: string;
  scope: string[];
}

export interface DimensionScore {
  name: "completeness" | "logic" | "content_quality" | "requirement_alignment";
  score: number;
  weight: number;
  feedback: string;
}

export interface EvaluationIssue {
  code: string;
  severity: "low" | "medium" | "high" | "blocking";
  scope: string[];
  description: string;
  suggestion: string;
}

export interface EvaluationResult {
  total_score: number;
  passed: boolean;
  threshold: number;
  hard_checks: HardCheck[];
  dimensions: DimensionScore[];
  issues: EvaluationIssue[];
  suggestions: string[];
}

export interface EvaluationResponse {
  task_id: string;
  version: number;
  revision_count: number;
  evaluation_result: EvaluationResult;
}

export interface Revision {
  id: string;
  task_id: string;
  revision_number: number;
  revision_type: "AUTO" | "USER" | "CHAT" | "UNDO";
  scope: string[];
  reason: string;
  before_slides: import("./content").SlideContent[];
  after_slides: import("./content").SlideContent[];
  score_before: number | null;
  score_after: number | null;
  created_at: string;
}

export interface RevisionListResponse {
  task_id: string;
  items: Revision[];
}

export interface EvaluationDecision {
  expected_version: number;
  action: "accept" | "refine" | "cancel";
  feedback?: string;
  scope?: string[];
}
