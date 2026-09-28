import type { Revision } from "./evaluation";

export type ChatTargetType =
  "outline_item" | "section" | "slide" | "whole_deck";
export type ChangeStatus =
  | "NEEDS_CLARIFICATION"
  | "NEEDS_CONFIRMATION"
  | "APPLIED"
  | "REJECTED"
  | "SUPERSEDED";

export interface ChatTarget {
  target_type: ChatTargetType;
  target_id?: string | null;
  label?: string | null;
}

export interface ChangeRequest {
  id: string;
  task_id: string;
  source_message_id: string;
  target_type: ChatTargetType;
  target_ids: string[];
  operation:
    "replace" | "rewrite" | "expand" | "shorten" | "reorder" | "regenerate";
  instruction: string;
  replacement_text?: string | null;
  risk_level: "local" | "wide" | "constraint_change";
  needs_clarification: boolean;
  clarification_question?: string | null;
  impact_scope: string[];
  affected_pages: number[];
  status: ChangeStatus;
  expected_task_version: number;
  created_at: string;
  resolved_at?: string | null;
}

export interface ChatMessage {
  id: string;
  task_id: string;
  role: "user" | "assistant";
  content: string;
  target?: ChatTarget | null;
  change_request?: ChangeRequest | null;
  revision_id?: string | null;
  can_undo: boolean;
  created_at: string;
}

export interface ChatHistoryResponse {
  task_id: string;
  items: ChatMessage[];
}

export interface SendChatMessageRequest {
  content: string;
  expected_task_version: number;
  target?: ChatTarget | null;
}

export interface ChatResult {
  task_id: string;
  status: ChangeStatus;
  user_message: ChatMessage;
  assistant_message: ChatMessage;
  change_request: ChangeRequest;
  revision_id?: string | null;
  task_version: number;
}

export interface UndoResult {
  task_id: string;
  revision: Revision;
  task_version: number;
  can_undo: boolean;
  assistant_message: ChatMessage;
}
