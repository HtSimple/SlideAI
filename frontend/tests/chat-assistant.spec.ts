import { flushPromises, mount } from "@vue/test-utils";
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getChatMessages: vi.fn(),
  sendChatMessage: vi.fn(),
  confirmChatChange: vi.fn(),
  undoChatRevision: vi.fn(),
}));

vi.mock("../src/api/chat", () => api);

import ChatAssistantDrawer from "../src/components/chat/ChatAssistantDrawer.vue";

function client() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

describe("ChatAssistantDrawer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getChatMessages.mockResolvedValue({ task_id: "task-1", items: [] });
    api.sendChatMessage.mockResolvedValue({ task_version: 6 });
    api.confirmChatChange.mockResolvedValue({ task_version: 6 });
    api.undoChatRevision.mockResolvedValue({ task_version: 7 });
  });

  it("keeps the selected page visible and sends a task-versioned message", async () => {
    const queryClient = client();
    const updated = vi.fn();
    const wrapper = mount(ChatAssistantDrawer, {
      props: {
        taskId: "task-1",
        taskVersion: 5,
        open: true,
        target: {
          target_type: "slide",
          target_id: "slide-8",
          label: "第 8 页",
        },
        onUpdated: updated,
      },
      global: { plugins: [[VueQueryPlugin, { queryClient }]] },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("当前对象：第 8 页");
    await wrapper.get("textarea").setValue("请突出这一页的行动建议");
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(api.sendChatMessage).toHaveBeenCalledWith("task-1", {
      content: "请突出这一页的行动建议",
      expected_task_version: 5,
      target: {
        target_type: "slide",
        target_id: "slide-8",
        label: "第 8 页",
      },
    });
    queryClient.clear();
    wrapper.unmount();
    expect(updated).toHaveBeenCalledOnce();
  });

  it("shows a confirmation card with affected page numbers", async () => {
    api.getChatMessages.mockResolvedValue({
      task_id: "task-1",
      items: [
        {
          id: "assistant-1",
          task_id: "task-1",
          role: "assistant",
          content: "此大纲修改会影响第 4 页。确认后只会重新生成这些页面。",
          target: null,
          change_request: {
            id: "change-1",
            task_id: "task-1",
            source_message_id: "user-1",
            target_type: "outline_item",
            target_ids: ["item-4"],
            operation: "replace",
            instruction: "修改第四点",
            replacement_text: "具体项目分析",
            risk_level: "wide",
            needs_clarification: false,
            clarification_question: null,
            impact_scope: ["slide-4"],
            affected_pages: [4],
            status: "NEEDS_CONFIRMATION",
            expected_task_version: 5,
            created_at: "2026-09-29T00:00:00Z",
            resolved_at: null,
          },
          revision_id: null,
          can_undo: false,
          created_at: "2026-09-29T00:00:00Z",
        },
      ],
    });
    const queryClient = client();
    const wrapper = mount(ChatAssistantDrawer, {
      props: { taskId: "task-1", taskVersion: 5, open: true },
      global: { plugins: [[VueQueryPlugin, { queryClient }]] },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("将修改第 4 页");
    await wrapper.get("button.chat-action--primary").trigger("click");
    await flushPromises();

    expect(api.confirmChatChange).toHaveBeenCalledWith("task-1", "change-1", 5);
    queryClient.clear();
    wrapper.unmount();
  });
});
