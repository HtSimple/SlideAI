import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("axios", () => ({
  default: {
    create: () => api,
  },
}));

import {
  confirmChatChange,
  getChatMessages,
  sendChatMessage,
  undoChatRevision,
} from "../src/api/chat";

describe("chat API client", () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    api.get.mockResolvedValue({ data: { items: [] } });
    api.post.mockResolvedValue({ data: {} });
  });

  it("uses task scoped routes and includes expected task versions", async () => {
    const target = {
      target_type: "slide" as const,
      target_id: "slide-8",
      label: "第 8 页",
    };
    await getChatMessages("task-8");
    await sendChatMessage("task-8", {
      content: "精炼结论",
      expected_task_version: 4,
      target,
    });
    await confirmChatChange("task-8", "change-1", 4);
    await undoChatRevision("task-8", "revision-1", 5);

    expect(api.get.mock.calls).toEqual([
      ["/api/v1/tasks/task-8/chat/messages"],
    ]);
    expect(api.post.mock.calls).toEqual([
      [
        "/api/v1/tasks/task-8/chat/messages",
        {
          content: "精炼结论",
          expected_task_version: 4,
          target,
        },
      ],
      [
        "/api/v1/tasks/task-8/changes/change-1/confirm",
        {
          expected_task_version: 4,
        },
      ],
      [
        "/api/v1/tasks/task-8/revisions/revision-1/undo",
        {
          expected_task_version: 5,
        },
      ],
    ]);
  });
});
