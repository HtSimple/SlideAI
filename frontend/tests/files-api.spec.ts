import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("axios", () => ({
  default: {
    create: () => api,
  },
}));

import {
  getFileLimits,
  getTaskFiles,
  removeTaskFile,
  uploadTaskFile,
} from "../src/api/files";

describe("file API client", () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    api.delete.mockReset();
  });

  it("loads configured limits and files within a task", async () => {
    api.get.mockResolvedValueOnce({ data: { max_files_per_task: 10 } });
    api.get.mockResolvedValueOnce({ data: [] });

    await getFileLimits();
    await getTaskFiles("task-1");

    expect(api.get).toHaveBeenNthCalledWith(1, "/api/v1/file-limits");
    expect(api.get).toHaveBeenNthCalledWith(2, "/api/v1/tasks/task-1/files");
  });

  it("uploads multipart content and removes a file in task scope", async () => {
    const file = new File(["source text"], "source.txt", {
      type: "text/plain",
    });
    api.post.mockResolvedValueOnce({ data: { id: "file-1" } });

    await uploadTaskFile("task-1", file);
    await removeTaskFile("task-1", "file-1");

    const [url, body, config] = api.post.mock.calls[0];
    expect(url).toBe("/api/v1/tasks/task-1/files");
    expect(body.get("file")).toBe(file);
    expect(config.timeout).toBe(120000);
    expect(api.delete).toHaveBeenCalledWith(
      "/api/v1/tasks/task-1/files/file-1",
    );
  });
});
