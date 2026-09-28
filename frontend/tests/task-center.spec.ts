import { flushPromises, mount } from "@vue/test-utils";
import { VueQueryPlugin, QueryClient } from "@tanstack/vue-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import TaskCenterView from "../src/views/TaskCenterView.vue";
import { getTasks } from "../src/api/tasks";

vi.mock("../src/api/tasks", () => ({ getTasks: vi.fn() }));

describe("task center", () => {
  beforeEach(() => vi.mocked(getTasks).mockReset());

  it("renders the returned task and its status", async () => {
    vi.mocked(getTasks).mockResolvedValue({
      items: [
        {
          id: "task-1",
          name: "Quarterly outlook",
          status: "DRAFT",
          current_stage: null,
          raw_requirement: {
            topic: "Quarterly outlook",
            target_page_count: 12,
          },
          model_preference: { mode: "auto", model_key: null },
          complexity: { tier: "balanced", total_score: 4, factors: {} },
          version: 1,
          created_at: "2026-09-28T10:00:00Z",
          updated_at: "2026-09-28T10:00:00Z",
        },
      ],
      total: 1,
      offset: 0,
      limit: 20,
      status_counts: { DRAFT: 1 },
    });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    const wrapper = mount(TaskCenterView, {
      global: {
        plugins: [[VueQueryPlugin, { queryClient: client }]],
        stubs: { RouterLink: { template: "<a><slot /></a>" } },
      },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("Quarterly outlook");
    expect(wrapper.text()).toContain("草稿");
    expect(getTasks).toHaveBeenCalledOnce();
    client.clear();
  });
});
