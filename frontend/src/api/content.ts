import { api } from "./client";
import type { MarkdownResponse, SlideListResponse } from "../types/content";

export async function getSlides(taskId: string): Promise<SlideListResponse> {
  const response = await api.get<SlideListResponse>(
    `/api/v1/tasks/${taskId}/slides`,
  );
  return response.data;
}

export async function getMarkdown(taskId: string): Promise<MarkdownResponse> {
  const response = await api.get<MarkdownResponse>(
    `/api/v1/tasks/${taskId}/markdown`,
  );
  return response.data;
}

export async function downloadMarkdown(taskId: string): Promise<Blob> {
  const response = await api.get<Blob>(
    `/api/v1/tasks/${taskId}/markdown/download`,
    { responseType: "blob" },
  );
  return response.data;
}
