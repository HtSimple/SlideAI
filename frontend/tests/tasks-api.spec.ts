import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("axios", () => ({
  default: {
    create: () => api,
  },
}));

import { createTask, getModels, getTasks } from "../src/api/tasks";

describe("task API client", () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
  });

  it("requests a paginated task list and model catalog", async () => {
    api.get.mockResolvedValueOnce({
      data: { items: [], total: 0, offset: 20, limit: 20 },
    });
    api.get.mockResolvedValueOnce({ data: [] });

    await getTasks({ offset: 20, limit: 20, status: "DRAFT" });
    await getModels();

    expect(api.get).toHaveBeenNthCalledWith(1, "/api/v1/tasks", {
      params: { offset: 20, limit: 20, status: "DRAFT" },
    });
    expect(api.get).toHaveBeenNthCalledWith(2, "/api/v1/models");
  });

  it("creates a task through the versioned API", async () => {
    const input = {
      raw_requirement: { topic: "AI trends", target_page_count: 12 },
      model_preference: { mode: "auto" as const },
    };
    api.post.mockResolvedValueOnce({
      data: { id: "task-id", status: "DRAFT", version: 1 },
    });

    await createTask(input);

    expect(api.post).toHaveBeenCalledWith("/api/v1/tasks", input);
  });
});
