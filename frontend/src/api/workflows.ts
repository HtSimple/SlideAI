import { api } from "./client";
import type {
  Outline,
  OutlineResponse,
  RequirementResponse,
  StructuredRequirement,
  WorkflowState,
} from "../types/workflow";

export async function startTask(taskId: string): Promise<WorkflowState> {
  const response = await api.post<WorkflowState>(
    `/api/v1/tasks/${taskId}/start`,
  );
  return response.data;
}

export async function getRequirement(
  taskId: string,
): Promise<RequirementResponse> {
  const response = await api.get<RequirementResponse>(
    `/api/v1/tasks/${taskId}/requirement`,
  );
  return response.data;
}

export async function updateRequirement(
  taskId: string,
  expectedVersion: number,
  structuredRequirement: StructuredRequirement,
): Promise<RequirementResponse> {
  const response = await api.put<RequirementResponse>(
    `/api/v1/tasks/${taskId}/requirement`,
    {
      expected_version: expectedVersion,
      structured_requirement: structuredRequirement,
    },
  );
  return response.data;
}

export async function confirmRequirement(
  taskId: string,
  expectedVersion: number,
): Promise<WorkflowState> {
  const response = await api.post<WorkflowState>(
    `/api/v1/tasks/${taskId}/requirement/confirm`,
    { expected_version: expectedVersion },
  );
  return response.data;
}

export async function getOutline(taskId: string): Promise<OutlineResponse> {
  const response = await api.get<OutlineResponse>(
    `/api/v1/tasks/${taskId}/outline`,
  );
  return response.data;
}

export async function updateOutline(
  taskId: string,
  expectedVersion: number,
  outline: Outline,
): Promise<OutlineResponse> {
  const response = await api.put<OutlineResponse>(
    `/api/v1/tasks/${taskId}/outline`,
    {
      expected_version: expectedVersion,
      outline,
    },
  );
  return response.data;
}

export async function confirmOutline(
  taskId: string,
  expectedVersion: number,
): Promise<WorkflowState> {
  const response = await api.post<WorkflowState>(
    `/api/v1/tasks/${taskId}/outline/confirm`,
    {
      expected_version: expectedVersion,
    },
  );
  return response.data;
}
