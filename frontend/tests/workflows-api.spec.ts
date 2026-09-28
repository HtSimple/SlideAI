import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
}));

vi.mock("axios", () => ({
  default: {
    create: () => api,
  },
}));

import {
  confirmOutline,
  confirmRequirement,
  getOutline,
  getRequirement,
  startTask,
  updateOutline,
  updateRequirement,
} from "../src/api/workflows";

describe("workflow API client", () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    api.put.mockReset();
    api.get.mockResolvedValue({ data: {} });
    api.post.mockResolvedValue({ data: {} });
    api.put.mockResolvedValue({ data: {} });
  });

  it("uses the versioned task-scoped API for every workflow operation", async () => {
    await startTask("task-1");
    await getRequirement("task-1");
    await updateRequirement("task-1", 2, {} as never);
    await confirmRequirement("task-1", 3);
    await getOutline("task-1");
    await updateOutline("task-1", 4, {} as never);
    await confirmOutline("task-1", 5);

    expect(api.post.mock.calls.map(([url]) => url)).toEqual([
      "/api/v1/tasks/task-1/start",
      "/api/v1/tasks/task-1/requirement/confirm",
      "/api/v1/tasks/task-1/outline/confirm",
    ]);
    expect(api.get.mock.calls.map(([url]) => url)).toEqual([
      "/api/v1/tasks/task-1/requirement",
      "/api/v1/tasks/task-1/outline",
    ]);
    expect(api.put.mock.calls.map(([url]) => url)).toEqual([
      "/api/v1/tasks/task-1/requirement",
      "/api/v1/tasks/task-1/outline",
    ]);
  });
});
