import { describe, expect, it } from "vitest";
import { resolveTaskRoute } from "../src/domain/task-routing";
import type { TaskRecord, TaskStatus } from "../src/types/tasks";

function task(status: TaskStatus): TaskRecord {
  return {
    id: "task-42",
    name: "Quarterly outlook",
    status,
    current_stage: null,
    raw_requirement: { topic: "Quarterly outlook", target_page_count: 12 },
    model_preference: { mode: "auto", model_key: null },
    complexity: { tier: "balanced", total_score: 4, factors: {} },
    version: 1,
    created_at: "2026-09-28T10:00:00Z",
    updated_at: "2026-09-28T10:00:00Z",
  };
}

describe("resolveTaskRoute", () => {
  it.each([
    ["DRAFT", "/tasks/task-42/edit"],
    ["FILES_PROCESSING", "/tasks/task-42/edit"],
    ["READY", "/tasks/task-42/edit"],
    ["WAITING_REQUIREMENT_INPUT", "/tasks/task-42/requirement"],
    ["WAITING_OUTLINE_CONFIRMATION", "/tasks/task-42/outline"],
    ["RUNNING", "/tasks/task-42/progress"],
    ["WAITING_USER_FEEDBACK", "/tasks/task-42/progress"],
    ["FAILED_RETRYABLE", "/tasks/task-42/progress"],
    ["FAILED_FINAL", "/tasks/task-42/progress"],
    ["CANCELLED", "/tasks/task-42/progress"],
    ["COMPLETED", "/tasks/task-42/result"],
  ] as const)("maps %s to its resumable page", (status, path) => {
    expect(resolveTaskRoute(task(status))).toBe(path);
  });
});
