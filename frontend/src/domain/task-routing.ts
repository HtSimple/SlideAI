import type { TaskRecord } from "../types/tasks";

export function resolveTaskRoute(task: TaskRecord): string {
  const taskPath = `/tasks/${task.id}`;
  switch (task.status) {
    case "DRAFT":
    case "FILES_PROCESSING":
    case "READY":
      return `${taskPath}/edit`;
    case "WAITING_REQUIREMENT_INPUT":
      return `${taskPath}/requirement`;
    case "WAITING_OUTLINE_CONFIRMATION":
      return `${taskPath}/outline`;
    case "COMPLETED":
      return `${taskPath}/result`;
    case "RUNNING":
    case "WAITING_USER_FEEDBACK":
    case "FAILED_RETRYABLE":
    case "FAILED_FINAL":
    case "CANCELLED":
      return `${taskPath}/progress`;
  }
}
