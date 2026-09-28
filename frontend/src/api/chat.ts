import { api } from "./client";
import type {
  ChatHistoryResponse,
  ChatResult,
  SendChatMessageRequest,
  UndoResult,
} from "../types/chat";

export async function getChatMessages(
  taskId: string,
): Promise<ChatHistoryResponse> {
  const response = await api.get<ChatHistoryResponse>(
    `/api/v1/tasks/${taskId}/chat/messages`,
  );
  return response.data;
}

export async function sendChatMessage(
  taskId: string,
  request: SendChatMessageRequest,
): Promise<ChatResult> {
  const response = await api.post<ChatResult>(
    `/api/v1/tasks/${taskId}/chat/messages`,
    request,
  );
  return response.data;
}

export async function confirmChatChange(
  taskId: string,
  changeId: string,
  expectedTaskVersion: number,
): Promise<ChatResult> {
  const response = await api.post<ChatResult>(
    `/api/v1/tasks/${taskId}/changes/${changeId}/confirm`,
    { expected_task_version: expectedTaskVersion },
  );
  return response.data;
}

export async function undoChatRevision(
  taskId: string,
  revisionId: string,
  expectedTaskVersion: number,
): Promise<UndoResult> {
  const response = await api.post<UndoResult>(
    `/api/v1/tasks/${taskId}/revisions/${revisionId}/undo`,
    { expected_task_version: expectedTaskVersion },
  );
  return response.data;
}
