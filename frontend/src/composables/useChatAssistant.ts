import { computed, ref, toValue, type MaybeRefOrGetter } from "vue";
import { useQuery, useQueryClient } from "@tanstack/vue-query";
import {
  confirmChatChange,
  getChatMessages,
  sendChatMessage,
  undoChatRevision,
} from "../api/chat";
import { apiErrorMessage } from "../api/client";
import type { ChatTarget } from "../types/chat";

export function useChatAssistant(options: {
  taskId: string;
  taskVersion: MaybeRefOrGetter<number>;
  open: MaybeRefOrGetter<boolean>;
  target: MaybeRefOrGetter<ChatTarget | null>;
  onUpdated: () => void;
}) {
  const queryClient = useQueryClient();
  const draft = ref("");
  const busy = ref(false);
  const error = ref("");
  const isOpen = computed(() => toValue(options.open));
  const historyQuery = useQuery({
    queryKey: ["chat", options.taskId],
    queryFn: () => getChatMessages(options.taskId),
    enabled: isOpen,
  });
  const messages = computed(() => historyQuery.data.value?.items ?? []);

  async function refreshAfterMutation(): Promise<void> {
    await queryClient.invalidateQueries({ queryKey: ["chat", options.taskId] });
    options.onUpdated();
  }

  async function send(): Promise<void> {
    const content = draft.value.trim();
    if (!content || busy.value) return;
    error.value = "";
    busy.value = true;
    try {
      await sendChatMessage(options.taskId, {
        content,
        expected_task_version: toValue(options.taskVersion),
        target: toValue(options.target),
      });
      draft.value = "";
      await refreshAfterMutation();
    } catch (reason) {
      error.value = apiErrorMessage(reason, "消息发送失败，请重试。");
    } finally {
      busy.value = false;
    }
  }

  async function confirm(changeId: string): Promise<void> {
    if (busy.value) return;
    error.value = "";
    busy.value = true;
    try {
      await confirmChatChange(
        options.taskId,
        changeId,
        toValue(options.taskVersion),
      );
      await refreshAfterMutation();
    } catch (reason) {
      error.value = apiErrorMessage(reason, "确认修改失败，请刷新后重试。");
    } finally {
      busy.value = false;
    }
  }

  async function undo(revisionId: string): Promise<void> {
    if (busy.value) return;
    error.value = "";
    busy.value = true;
    try {
      await undoChatRevision(
        options.taskId,
        revisionId,
        toValue(options.taskVersion),
      );
      await refreshAfterMutation();
    } catch (reason) {
      error.value = apiErrorMessage(reason, "撤销失败，请刷新后重试。");
    } finally {
      busy.value = false;
    }
  }

  return { draft, busy, error, historyQuery, messages, send, confirm, undo };
}
