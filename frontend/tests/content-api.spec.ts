import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("axios", () => ({
  default: {
    create: () => api,
  },
}));

import { downloadMarkdown, getMarkdown, getSlides } from "../src/api/content";

describe("content API client", () => {
  beforeEach(() => {
    api.get.mockReset();
    api.get.mockResolvedValue({ data: {} });
  });

  it("uses task-scoped content routes and requests Markdown as UTF-8 blob", async () => {
    await getSlides("task-8");
    await getMarkdown("task-8");
    await downloadMarkdown("task-8");

    expect(api.get.mock.calls).toEqual([
      ["/api/v1/tasks/task-8/slides"],
      ["/api/v1/tasks/task-8/markdown"],
      ["/api/v1/tasks/task-8/markdown/download", { responseType: "blob" }],
    ]);
  });
});
