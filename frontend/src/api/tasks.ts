import { api } from "./client";
import type {
  CreateTaskInput,
  ModelOption,
  TaskPage,
  TaskRecord,
} from "../types/tasks";

export interface TaskQuery {
  offset?: number;
  limit?: number;
  status?: string;
  q?: string;
}

export async function getTasks(query: TaskQuery = {}): Promise<TaskPage> {
  const response = await api.get<TaskPage>("/api/v1/tasks", { params: query });
  return response.data;
}

export async function getTask(taskId: string): Promise<TaskRecord> {
  const response = await api.get<TaskRecord>(`/api/v1/tasks/${taskId}`);
  return response.data;
}

export async function getModels(): Promise<ModelOption[]> {
  const response = await api.get<ModelOption[]>("/api/v1/models");
  return response.data;
}

export async function createTask(input: CreateTaskInput): Promise<TaskRecord> {
  const response = await api.post<TaskRecord>("/api/v1/tasks", input);
  return response.data;
}

export async function patchTask(
  taskId: string,
  expectedVersion: number,
  changes: Partial<CreateTaskInput> & { name?: string },
): Promise<TaskRecord> {
  const response = await api.patch<TaskRecord>(`/api/v1/tasks/${taskId}`, {
    expected_version: expectedVersion,
    ...changes,
  });
  return response.data;
}

export async function deleteTask(taskId: string): Promise<void> {
  await api.delete(`/api/v1/tasks/${taskId}`);
}
