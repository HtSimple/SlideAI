export type SourceUsage = "required" | "preferred" | "optional";
export type DomainExpertise = "general" | "professional" | "specialized";
export type AnalysisDepth = "overview" | "comparison" | "strategic";

export interface StructuredRequirement {
  topic: string | null;
  target_page_count: number | null;
  scenario: string | null;
  audience: string | null;
  style: string | null;
  constraints: string[];
  language: string;
  source_usage: SourceUsage;
  original_text: string | null;
  domain_expertise: DomainExpertise;
  analysis_depth: AnalysisDepth;
}

export interface OutlineItem {
  id: string;
  title: string;
  objective: string;
  page_count: number;
}

export interface OutlineSection {
  id: string;
  title: string;
  objective: string;
  page_count: number;
  items: OutlineItem[];
}

export interface Outline {
  title: string;
  sections: OutlineSection[];
}

export interface WorkflowState {
  task_id: string;
  status: string;
  current_stage: string | null;
  version: number;
}

export interface RequirementResponse extends WorkflowState {
  structured_requirement: StructuredRequirement | null;
  missing_fields: string[];
}

export interface OutlineIssue {
  code: string;
  message: string;
  target_id?: string | null;
}

export interface OutlineResponse extends WorkflowState {
  outline: Outline | null;
  issues: OutlineIssue[];
}
