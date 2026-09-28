import { api } from "./client";
import type {
  EvaluationDecision,
  EvaluationResponse,
  RevisionListResponse,
} from "../types/evaluation";

export async function getEvaluation(
  taskId: string,
): Promise<EvaluationResponse> {
  const response = await api.get<EvaluationResponse>(
    `/api/v1/tasks/${taskId}/evaluation`,
  );
  return response.data;
}

export async function getRevisions(
  taskId: string,
): Promise<RevisionListResponse> {
  const response = await api.get<RevisionListResponse>(
    `/api/v1/tasks/${taskId}/revisions`,
  );
  return response.data;
}

export async function submitEvaluationDecision(
  taskId: string,
  decision: EvaluationDecision,
): Promise<void> {
  await api.post(`/api/v1/tasks/${taskId}/evaluation/decision`, decision);
}
