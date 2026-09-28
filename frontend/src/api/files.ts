import { api } from "./client";
import type { FileLimits, SourceFile } from "../types/files";

export async function getFileLimits(): Promise<FileLimits> {
  const response = await api.get<FileLimits>("/api/v1/file-limits");
  return response.data;
}

export async function getTaskFiles(taskId: string): Promise<SourceFile[]> {
  const response = await api.get<SourceFile[]>(`/api/v1/tasks/${taskId}/files`);
  return response.data;
}

export async function uploadTaskFile(
  taskId: string,
  file: File,
): Promise<SourceFile> {
  const body = new FormData();
  body.append("file", file);
  const response = await api.post<SourceFile>(
    `/api/v1/tasks/${taskId}/files`,
    body,
    {
      timeout: 120000,
    },
  );
  return response.data;
}

export async function retryTaskFile(
  taskId: string,
  fileId: string,
): Promise<SourceFile> {
  const response = await api.post<SourceFile>(
    `/api/v1/tasks/${taskId}/files/${fileId}/retry`,
  );
  return response.data;
}

export async function removeTaskFile(
  taskId: string,
  fileId: string,
): Promise<void> {
  await api.delete(`/api/v1/tasks/${taskId}/files/${fileId}`);
}
