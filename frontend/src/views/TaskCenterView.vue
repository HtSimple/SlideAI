<script setup lang="ts">
import { computed, ref } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { RouterLink } from "vue-router";
import { getTasks } from "../api/tasks";
import { resolveTaskRoute } from "../domain/task-routing";
import type { TaskRecord, TaskStatus } from "../types/tasks";

const pageSize = 20;
const offset = ref(0);
const selectedStatus = ref<string | undefined>();
const searchInput = ref("");
const searchQuery = ref("");
const taskQuery = useQuery({
  queryKey: computed(() => [
    "tasks",
    offset.value,
    selectedStatus.value,
    searchQuery.value,
  ]),
  queryFn: () =>
    getTasks({
      offset: offset.value,
      limit: pageSize,
      ...(selectedStatus.value ? { status: selectedStatus.value } : {}),
      ...(searchQuery.value ? { q: searchQuery.value } : {}),
    }),
});

const tasks = computed(() => taskQuery.data.value?.items ?? []);
const total = computed(() => taskQuery.data.value?.total ?? 0);
const counts = computed(() => {
  const statusCounts = taskQuery.data.value?.status_counts ?? {};
  const waiting = Object.entries(statusCounts)
    .filter(([status]) => status.startsWith("WAITING_"))
    .reduce((totalCount, [, count]) => totalCount + count, 0);
  return [
    {
      label: "进行中",
      filter: "RUNNING",
      count: (statusCounts.RUNNING ?? 0) + (statusCounts.FILES_PROCESSING ?? 0),
    },
    {
      label: "等待处理",
      filter: "WAITING",
      count: waiting,
    },
    {
      label: "已完成",
      filter: "COMPLETED",
      count: statusCounts.COMPLETED ?? 0,
    },
    {
      label: "失败可重试",
      filter: "FAILED_RETRYABLE",
      count: statusCounts.FAILED_RETRYABLE ?? 0,
    },
  ];
});

const statusLabel: Record<TaskStatus, string> = {
  DRAFT: "草稿",
  FILES_PROCESSING: "资料处理中",
  READY: "已就绪",
  WAITING_REQUIREMENT_INPUT: "等待需求确认",
  WAITING_OUTLINE_CONFIRMATION: "等待大纲确认",
  RUNNING: "进行中",
  WAITING_USER_FEEDBACK: "等待处理",
  FAILED_RETRYABLE: "失败可重试",
  FAILED_FINAL: "失败",
  CANCELLED: "已取消",
  COMPLETED: "已完成",
};

function applySearch(): void {
  searchQuery.value = searchInput.value.trim();
  offset.value = 0;
}

function filterByStatus(filter: string): void {
  selectedStatus.value = filter === "WAITING" ? "WAITING_" : filter;
  offset.value = 0;
}

function resolveAction(task: TaskRecord): string {
  if (task.status === "DRAFT" || task.status === "READY") return "继续编辑";
  if (task.status === "COMPLETED") return "查看结果";
  if (task.status === "FAILED_RETRYABLE") return "查看状态";
  if (task.status.startsWith("WAITING_")) return "继续处理";
  if (task.status === "RUNNING" || task.status === "FILES_PROCESSING")
    return "查看进度";
  return "查看详情";
}

function taskRoute(task: TaskRecord): string {
  return resolveTaskRoute(task);
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
</script>

<template>
  <section class="task-center" aria-labelledby="page-title">
    <div class="task-center__heading">
      <div>
        <p class="eyebrow">工作台</p>
        <h1 id="page-title">任务中心</h1>
        <p class="page-intro">查看、恢复和管理演示文稿内容生成任务</p>
      </div>
      <RouterLink class="button button--primary" to="/tasks/new"
        >创建新任务</RouterLink
      >
    </div>

    <div class="status-grid" aria-label="任务状态摘要">
      <button
        v-for="item in counts"
        :key="item.filter"
        class="status-card"
        :class="{
          'status-card--active':
            selectedStatus === item.filter ||
            (item.filter === 'WAITING' && selectedStatus === 'WAITING_'),
        }"
        type="button"
        @click="filterByStatus(item.filter)"
      >
        <span>{{ item.label }}</span
        ><strong>{{ item.count }}</strong>
      </button>
    </div>

    <section class="task-panel" aria-labelledby="list-title">
      <div class="task-panel__heading">
        <div>
          <h2 id="list-title">全部任务</h2>
          <p>共 {{ total }} 个任务</p>
        </div>
        <form class="search" role="search" @submit.prevent="applySearch">
          <label class="sr-only" for="task-search">搜索任务</label
          ><input
            id="task-search"
            v-model="searchInput"
            type="search"
            placeholder="搜索任务名称"
          /><button class="button button--secondary" type="submit">搜索</button>
        </form>
      </div>

      <div v-if="taskQuery.isPending.value" class="table-message" role="status">
        正在加载任务…
      </div>
      <div
        v-else-if="taskQuery.isError.value"
        class="table-message table-message--error"
        role="alert"
      >
        <p>暂时无法加载任务，请检查服务状态后重试。</p>
        <button
          class="button button--secondary"
          type="button"
          @click="taskQuery.refetch()"
        >
          重新加载
        </button>
      </div>
      <div v-else-if="tasks.length === 0" class="empty-state">
        <div class="empty-state__mark" aria-hidden="true">文</div>
        <h3>
          {{
            searchQuery || selectedStatus ? "没有匹配的任务" : "还没有生成任务"
          }}
        </h3>
        <p>
          {{
            searchQuery || selectedStatus
              ? "调整搜索词或筛选条件后重试。"
              : "创建一个任务，填写演示文稿需求并生成结构化文字内容。"
          }}
        </p>
        <RouterLink
          v-if="!searchQuery && !selectedStatus"
          class="button button--secondary"
          to="/tasks/new"
          >创建新任务</RouterLink
        >
      </div>
      <div v-else class="table-scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">任务名称</th>
              <th scope="col">状态</th>
              <th scope="col">当前阶段</th>
              <th scope="col">目标页数</th>
              <th scope="col">模型偏好</th>
              <th scope="col">更新时间</th>
              <th scope="col"><span class="sr-only">操作</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in tasks" :key="task.id">
              <th scope="row">
                <RouterLink class="task-name" :to="taskRoute(task)">{{
                  task.name
                }}</RouterLink>
              </th>
              <td>
                <span
                  class="status-pill"
                  :class="`status-pill--${task.status.toLowerCase()}`"
                  >{{ statusLabel[task.status] }}</span
                >
              </td>
              <td>{{ task.current_stage || "—" }}</td>
              <td>{{ task.raw_requirement.target_page_count }} 页</td>
              <td>
                {{
                  task.model_preference.mode === "auto"
                    ? "自动选择"
                    : task.model_preference.model_key
                }}
              </td>
              <td>{{ formatDate(task.updated_at) }}</td>
              <td>
                <RouterLink class="action-link" :to="taskRoute(task)">{{
                  resolveAction(task)
                }}</RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <footer v-if="total > pageSize" class="pagination" aria-label="任务分页">
        <span
          >第 {{ Math.floor(offset / pageSize) + 1 }} 页，共
          {{ Math.ceil(total / pageSize) }} 页</span
        >
        <div>
          <button
            class="button button--secondary"
            type="button"
            :disabled="offset === 0"
            @click="offset -= pageSize"
          >
            上一页</button
          ><button
            class="button button--secondary"
            type="button"
            :disabled="offset + pageSize >= total"
            @click="offset += pageSize"
          >
            下一页
          </button>
        </div>
      </footer>
    </section>
  </section>
</template>

<style scoped>
.task-center__heading,
.task-panel__heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
}
.task-center__heading {
  margin-bottom: 24px;
}
.task-center {
  width: 100%;
  min-width: 0;
}
.eyebrow {
  margin: 0 0 6px;
  color: var(--color-primary-700);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
h1 {
  margin: 0;
  color: var(--color-text-strong);
  font-size: 30px;
  line-height: 1.35;
}
.page-intro,
.task-panel__heading p {
  margin: 7px 0 0;
  color: var(--color-text-muted);
  font-size: 14px;
}
.button {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  justify-content: center;
  padding: 0 15px;
  border: 1px solid var(--color-primary-600);
  border-radius: var(--radius-control);
  font: 600 14px inherit;
  text-decoration: none;
  cursor: pointer;
}
.button:focus-visible,
.status-card:focus-visible,
input:focus-visible,
.action-link:focus-visible,
.task-name:focus-visible {
  outline: 3px solid var(--color-focus);
  outline-offset: 2px;
}
.button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.button--primary {
  background: var(--color-primary-600);
  color: #fff;
}
.button--secondary {
  background: #fff;
  color: var(--color-primary-700);
}
.status-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 22px;
}
.status-card {
  display: flex;
  min-height: 92px;
  align-items: flex-start;
  justify-content: space-between;
  padding: 18px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
  color: var(--color-text-muted);
  text-align: left;
  cursor: pointer;
}
.status-card strong {
  color: var(--color-text-strong);
  font-size: 28px;
}
.status-card--active {
  border-color: var(--color-primary-600);
  box-shadow: 0 0 0 2px
    color-mix(in srgb, var(--color-primary-600) 16%, transparent);
}
.task-panel {
  max-width: 100%;
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
}
.task-panel__heading {
  padding: 20px 22px;
  border-bottom: 1px solid var(--color-border);
}
.task-panel__heading h2 {
  margin: 0;
  color: var(--color-text-strong);
  font-size: 18px;
}
.search {
  display: flex;
  gap: 8px;
}
.search input {
  width: 240px;
  min-height: 40px;
  padding: 0 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  font: inherit;
}
.table-scroll {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
  font-size: 13px;
}
th,
td {
  padding: 14px 16px;
  border-bottom: 1px solid var(--color-border);
  white-space: nowrap;
}
thead th {
  background: #f8fafc;
  color: var(--color-text-muted);
  font-size: 12px;
  font-weight: 600;
}
tbody th {
  font-weight: 600;
}
.task-name {
  color: var(--color-text-strong);
  text-decoration: none;
}
.task-name:hover,
.action-link:hover {
  text-decoration: underline;
}
.action-link {
  color: var(--color-primary-700);
  font-weight: 600;
  text-decoration: none;
}
.status-pill {
  display: inline-flex;
  padding: 4px 9px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #475569;
  font-size: 12px;
}
.status-pill--completed {
  background: #ecfdf5;
  color: #047857;
}
.status-pill--running,
.status-pill--files_processing {
  background: #eff6ff;
  color: #1d4ed8;
}
.status-pill--failed_retryable,
.status-pill--failed_final {
  background: #fff1f2;
  color: #be123c;
}
.empty-state,
.table-message {
  display: flex;
  min-height: 280px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 30px;
  text-align: center;
}
.empty-state__mark {
  display: grid;
  width: 48px;
  height: 48px;
  place-items: center;
  border-radius: 12px;
  background: var(--color-primary-050);
  color: var(--color-primary-700);
  font-size: 24px;
  font-weight: 600;
}
.empty-state h3 {
  margin: 17px 0 0;
  color: var(--color-text-strong);
  font-size: 18px;
}
.empty-state p,
.table-message p {
  max-width: 450px;
  margin: 8px 0 18px;
  color: var(--color-text-muted);
  font-size: 14px;
  line-height: 1.6;
}
.table-message--error {
  color: #b42318;
}
.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  color: var(--color-text-muted);
  font-size: 13px;
}
.pagination div {
  display: flex;
  gap: 8px;
}
.sr-only {
  position: fixed;
  top: 0;
  left: 0;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  clip-path: inset(50%);
}
@media (max-width: 900px) {
  .status-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .task-panel__heading {
    align-items: flex-start;
    flex-direction: column;
  }
  .search {
    width: 100%;
  }
  .search input {
    flex: 1;
  }
}
@media (max-width: 560px) {
  .task-center__heading {
    align-items: stretch;
    flex-direction: column;
  }
  .task-center__heading .button {
    align-self: flex-start;
  }
  .status-grid {
    gap: 9px;
  }
  .status-card {
    min-height: 76px;
    padding: 13px;
  }
  .status-card strong {
    font-size: 24px;
  }
  .pagination {
    align-items: flex-start;
    flex-direction: column;
    gap: 12px;
  }
  .pagination div {
    width: 100%;
  }
  .pagination button {
    flex: 1;
  }
}
</style>
