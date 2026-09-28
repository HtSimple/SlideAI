<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { RouterLink, useRoute, useRouter } from "vue-router";
import { getTask } from "../api/tasks";
import { resolveTaskRoute } from "../domain/task-routing";
import { apiErrorMessage } from "../api/client";
import { submitEvaluationDecision } from "../api/evaluation";
import { getSlides } from "../api/content";
import { cancelWorkflow } from "../api/workflows";

const route = useRoute();
const router = useRouter();
const taskId = String(route.params.taskId);
const hidden = ref(false);
const active = ref(false);
const taskQuery = useQuery({
  queryKey: ["task", taskId],
  queryFn: () => getTask(taskId),
  refetchInterval: computed(() =>
    active.value ? (hidden.value ? 10_000 : 2_000) : false,
  ),
  refetchIntervalInBackground: true,
});
const task = computed(() => taskQuery.data.value);
const progress = computed(() => task.value?.generation_progress);
const evaluation = computed(() => task.value?.evaluation_result);
const feedback = ref("");
const selectedScope = ref<string[]>([]);
const actionBusy = ref(false);
const actionMessage = ref("");
const slidesQuery = useQuery({
  queryKey: ["slides", taskId],
  queryFn: () => getSlides(taskId),
  enabled: computed(() => task.value?.status === "WAITING_USER_FEEDBACK"),
});

const stages = [
  "需求解析",
  "大纲规划",
  "资料检索",
  "内容生成",
  "质量评估",
  "完成",
];
const stageIndex: Record<string, number> = {
  analyze_requirement: 0,
  requirement_review: 0,
  plan_outline: 1,
  outline_review: 1,
  retrieve_context: 2,
  write_slides: 3,
  generate_markdown: 3,
  evaluate: 4,
  revise: 4,
  completed: 5,
};
const currentStageIndex = computed(() => {
  if (task.value?.status === "COMPLETED") return stages.length - 1;
  return stageIndex[task.value?.current_stage ?? ""] ?? 3;
});
const isRunning = computed(() => task.value?.status === "RUNNING");
const statusLabel = computed(() => {
  const labels: Record<string, string> = {
    FILES_PROCESSING: "资料处理中",
    RUNNING: "正在生成",
    WAITING_USER_FEEDBACK: "等待你处理",
    FAILED_RETRYABLE: "生成中断，可恢复",
    FAILED_FINAL: "生成失败",
    CANCELLED: "已取消",
  };
  return task.value
    ? (labels[task.value.status] ?? task.value.status)
    : "读取中";
});

watch(
  () => task.value,
  (value) => {
    if (!value) return;
    active.value = value.status === "RUNNING";
    const destination = resolveTaskRoute(value);
    if (route.path !== destination) void router.replace(destination);
  },
  { immediate: true },
);

function updateVisibility(): void {
  hidden.value = globalThis.document.visibilityState === "hidden";
}

async function decideEvaluation(
  action: "accept" | "refine" | "cancel",
): Promise<void> {
  if (!task.value || actionBusy.value) return;
  if (action === "refine" && !feedback.value.trim()) {
    actionMessage.value = "请先填写希望改进的内容。";
    return;
  }
  actionBusy.value = true;
  actionMessage.value = "";
  try {
    await submitEvaluationDecision(taskId, {
      expected_version: task.value.version,
      action,
      ...(action === "refine"
        ? { feedback: feedback.value.trim(), scope: selectedScope.value }
        : {}),
    });
    active.value = true;
    feedback.value = "";
    await taskQuery.refetch();
  } catch (error) {
    actionMessage.value = apiErrorMessage(error, "提交评估操作失败，请重试。");
  } finally {
    actionBusy.value = false;
  }
}

async function cancelRunningWorkflow(): Promise<void> {
  if (!task.value || !isRunning.value || actionBusy.value) return;
  actionBusy.value = true;
  actionMessage.value = "";
  try {
    await cancelWorkflow(taskId, task.value.version);
    active.value = false;
    await taskQuery.refetch();
  } catch (error) {
    actionMessage.value = apiErrorMessage(
      error,
      "取消任务失败，请刷新后重试。",
    );
  } finally {
    actionBusy.value = false;
  }
}

onMounted(() => {
  updateVisibility();
  globalThis.document.addEventListener("visibilitychange", updateVisibility);
});

onUnmounted(() => {
  globalThis.document.removeEventListener("visibilitychange", updateVisibility);
});
</script>

<template>
  <main class="progress-page" aria-labelledby="page-title">
    <header v-if="task" class="task-context">
      <div>
        <RouterLink class="back-link" to="/tasks">← 返回任务中心</RouterLink>
        <h1 id="page-title" :title="task.name">{{ task.name }}</h1>
        <p>
          目标 {{ task.raw_requirement.target_page_count }} 页
          <span aria-hidden="true">·</span> 版本 {{ task.version }}
        </p>
      </div>
      <span
        class="status-pill"
        :class="`status-pill--${task.status.toLowerCase()}`"
      >
        {{ statusLabel }}
      </span>
    </header>
    <div v-else class="task-context task-context--loading" role="status">
      正在读取任务状态…
    </div>

    <div class="workflow-strip" aria-label="工作流进度">
      <div
        v-for="(stage, index) in stages"
        :key="stage"
        class="workflow-strip__item"
        :class="{
          'workflow-strip__item--done': index < currentStageIndex,
          'workflow-strip__item--active':
            index === currentStageIndex && task?.status === 'RUNNING',
        }"
      >
        <span class="workflow-strip__number">{{
          index < currentStageIndex ? "✓" : index + 1
        }}</span>
        <span>{{ stage }}</span>
      </div>
    </div>

    <div v-if="taskQuery.isPending.value" class="progress-panel" role="status">
      正在读取生成进度…
    </div>
    <div
      v-else-if="taskQuery.isError.value"
      class="progress-panel progress-panel--error"
      role="alert"
    >
      <h2>暂时无法读取任务</h2>
      <p>服务没有返回任务状态，请重试。任务状态不会因这次读取失败而改变。</p>
      <button
        class="button button--secondary"
        type="button"
        @click="taskQuery.refetch()"
      >
        重新加载
      </button>
    </div>
    <div v-else-if="task" class="progress-layout">
      <section
        class="progress-panel run-history"
        aria-labelledby="history-title"
      >
        <h2 id="history-title">生成进度</h2>
        <ol class="run-history__list">
          <li
            v-for="(stage, index) in stages"
            :key="stage"
            :class="{
              'run-history__item--done': index < currentStageIndex,
              'run-history__item--active':
                index === currentStageIndex && isRunning,
            }"
          >
            <span class="run-history__mark" aria-hidden="true">{{
              index < currentStageIndex ? "✓" : index + 1
            }}</span>
            <div>
              <strong>{{ stage }}</strong>
              <small>
                {{
                  index < currentStageIndex
                    ? "已完成"
                    : index === currentStageIndex && isRunning
                      ? "执行中"
                      : "等待中"
                }}
              </small>
            </div>
          </li>
        </ol>
      </section>

      <section class="progress-panel current-status" aria-live="polite">
        <span
          class="current-status__symbol"
          :class="{ 'current-status__symbol--busy': isRunning }"
          aria-hidden="true"
        >
          {{
            task.status === "RUNNING"
              ? "···"
              : task.status === "CANCELLED"
                ? "—"
                : "!"
          }}
        </span>
        <h2>{{ isRunning ? "正在生成逐页文字内容" : statusLabel }}</h2>
        <p v-if="progress" class="page-count" role="status">
          已完成 {{ progress.completed_pages }} /
          {{ progress.total_pages }} 页文字内容
        </p>
        <p v-else-if="task.status === 'RUNNING'">
          正在准备生成内容，完成的页面会在这里持续显示。
        </p>
        <p v-else-if="task.status === 'WAITING_USER_FEEDBACK'">
          自动修订已达到上限。当前内容、评估结果和修订记录均已保存。
        </p>
        <p v-else-if="task.status.startsWith('FAILED_')">
          已保存的任务内容仍可查看。可返回任务中心检查并恢复任务。
        </p>
        <p v-else-if="task.status === 'CANCELLED'">
          任务已停止，取消前的进度仍然保留。
        </p>
        <p v-else>资料处理和页面生成状态会显示在此处。</p>
        <p v-if="progress && progress.total_batches > 0" class="batch-count">
          已完成 {{ progress.completed_batches }} /
          {{ progress.total_batches }} 批
        </p>
        <RouterLink class="button button--secondary" to="/tasks"
          >返回任务中心</RouterLink
        >
        <button
          v-if="isRunning"
          class="button button--secondary"
          type="button"
          :disabled="actionBusy"
          @click="cancelRunningWorkflow"
        >
          {{ actionBusy ? "正在取消…" : "取消任务" }}
        </button>
        <p v-if="actionMessage" role="alert">{{ actionMessage }}</p>
        <section
          v-if="task.status === 'WAITING_USER_FEEDBACK' && evaluation"
          class="evaluation-decision"
          aria-labelledby="decision-title"
        >
          <h3 id="decision-title">质量评估：{{ evaluation.total_score }} 分</h3>
          <ul v-if="evaluation.issues.length" class="decision-issues">
            <li
              v-for="issue in evaluation.issues"
              :key="issue.code + issue.description"
            >
              <strong>{{ issue.description }}</strong>
              <span>{{ issue.suggestion }}</span>
            </li>
          </ul>
          <fieldset
            v-if="slidesQuery.data.value?.items.length"
            class="scope-picker"
          >
            <legend>重新生成范围（可选）</legend>
            <label
              v-for="slide in slidesQuery.data.value.items"
              :key="slide.id"
            >
              <input
                v-model="selectedScope"
                type="checkbox"
                :value="slide.id"
              />
              第 {{ slide.page_number }} 页：{{ slide.title }}
            </label>
          </fieldset>
          <label class="feedback-field">
            修改意见
            <textarea
              v-model="feedback"
              rows="3"
              maxlength="2000"
              placeholder="描述希望优先改进的内容；留空范围时会按评估问题选择页面。"
            />
          </label>
          <div class="decision-actions">
            <button
              class="button button--secondary"
              type="button"
              :disabled="actionBusy"
              @click="decideEvaluation('cancel')"
            >
              取消任务
            </button>
            <button
              class="button button--secondary"
              type="button"
              :disabled="actionBusy"
              @click="decideEvaluation('accept')"
            >
              接受当前结果
            </button>
            <button
              class="button button--primary"
              type="button"
              :disabled="actionBusy"
              @click="decideEvaluation('refine')"
            >
              {{ actionBusy ? "正在提交…" : "提交意见并继续" }}
            </button>
          </div>
          <p v-if="actionMessage" role="alert">{{ actionMessage }}</p>
        </section>
      </section>
    </div>
  </main>
</template>

<style scoped>
.progress-page {
  max-width: 1280px;
  margin: 0 auto;
}
.task-context {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 22px;
}
.task-context h1 {
  max-width: min(70vw, 800px);
  overflow: hidden;
  margin: 10px 0 2px;
  color: var(--color-text-strong);
  font-size: clamp(22px, 3vw, 30px);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.task-context p {
  margin: 0;
  color: var(--color-text-muted);
}
.back-link {
  color: var(--color-primary-700);
  font-weight: 650;
  text-decoration: none;
}
.status-pill {
  flex: none;
  padding: 6px 12px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface);
  color: var(--color-text);
  font-weight: 650;
}
.workflow-strip {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 20px;
}
.workflow-strip__item {
  display: flex;
  align-items: center;
  gap: 9px;
  min-height: 58px;
  padding: 10px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: var(--color-surface);
  color: var(--color-text-muted);
}
.workflow-strip__number {
  display: grid;
  width: 25px;
  height: 25px;
  flex: none;
  place-items: center;
  border: 1px solid var(--color-border-strong);
  border-radius: 50%;
  font-weight: 700;
}
.workflow-strip__item--done,
.workflow-strip__item--active {
  border-color: #a9d4f7;
  background: var(--color-primary-050);
  color: var(--color-primary-800);
}
.workflow-strip__item--done .workflow-strip__number,
.workflow-strip__item--active .workflow-strip__number {
  border-color: var(--color-primary-600);
  background: var(--color-primary-600);
  color: #fff;
}
.progress-layout {
  display: grid;
  grid-template-columns: minmax(270px, 0.8fr) minmax(0, 1.2fr);
  align-items: start;
  gap: 18px;
}
.progress-panel {
  padding: 24px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
  box-shadow: var(--shadow-panel);
}
.progress-panel h2 {
  margin: 0;
  color: var(--color-text-strong);
  font-size: 20px;
}
.run-history__list {
  display: grid;
  gap: 0;
  padding: 0;
  margin: 20px 0 0;
  list-style: none;
}
.run-history__list li {
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 62px;
  color: var(--color-text-muted);
}
.run-history__list li:not(:last-child)::after {
  position: absolute;
  top: 42px;
  bottom: -4px;
  left: 14px;
  width: 1px;
  background: var(--color-border);
  content: "";
}
.run-history__mark {
  z-index: 1;
  display: grid;
  width: 29px;
  height: 29px;
  flex: none;
  place-items: center;
  border: 1px solid var(--color-border-strong);
  border-radius: 50%;
  background: var(--color-surface);
  font-weight: 700;
}
.run-history__item--done,
.run-history__item--active {
  color: var(--color-text-strong) !important;
}
.run-history__item--done .run-history__mark,
.run-history__item--active .run-history__mark {
  border-color: var(--color-primary-600);
  background: var(--color-primary-600);
  color: #fff;
}
.run-history__list li div {
  display: grid;
  gap: 2px;
}
.run-history__list small {
  color: var(--color-text-muted);
}
.current-status {
  display: grid;
  justify-items: center;
  gap: 14px;
  min-height: 300px;
  padding: 48px 32px;
  text-align: center;
}
.current-status p {
  max-width: 560px;
  margin: 0;
  color: var(--color-text-muted);
}
.current-status .page-count {
  color: var(--color-primary-800);
  font-size: 20px;
  font-weight: 700;
}
.batch-count {
  font-size: 13px;
}
.current-status__symbol {
  display: grid;
  width: 56px;
  height: 56px;
  place-items: center;
  border-radius: 50%;
  background: var(--color-warning-bg);
  color: #855100;
  font-size: 28px;
  font-weight: 800;
}
.current-status__symbol--busy {
  background: var(--color-primary-100);
  color: var(--color-primary-700);
  animation: pulse 1.5s ease-in-out infinite;
}
.progress-panel--error {
  display: grid;
  justify-items: start;
  gap: 12px;
  border-color: #f3bdc5;
  background: var(--color-danger-bg);
}
.evaluation-decision {
  display: grid;
  width: 100%;
  gap: 12px;
  padding: 16px;
  border: 1px solid var(--color-border);
  border-radius: 10px;
  background: #fff;
  text-align: left;
}
.evaluation-decision h3 {
  font-size: 17px;
}
.decision-issues,
.scope-picker {
  display: grid;
  gap: 9px;
  padding: 0;
  margin: 0;
  list-style: none;
}
.decision-issues li {
  display: grid;
  gap: 4px;
  color: var(--color-text-muted);
}
.decision-issues strong {
  color: var(--color-text-strong);
}
.scope-picker {
  padding: 12px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
}
.scope-picker legend {
  padding: 0 5px;
  font-weight: 650;
}
.scope-picker label,
.feedback-field {
  display: grid;
  gap: 6px;
  color: var(--color-text-strong);
  text-align: left;
}
.scope-picker label {
  grid-template-columns: auto 1fr;
  align-items: center;
  font-size: 13px;
}
.feedback-field textarea {
  width: 100%;
  resize: vertical;
  padding: 10px;
  border: 1px solid var(--color-border-strong);
  border-radius: 8px;
  color: var(--color-text-strong);
  font: inherit;
}
.decision-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 9px;
}
.button {
  display: inline-flex;
  min-height: 42px;
  align-items: center;
  justify-content: center;
  padding: 0 16px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  background: #fff;
  color: var(--color-text-strong);
  font: inherit;
  font-weight: 650;
  text-decoration: none;
  cursor: pointer;
}
@keyframes pulse {
  50% {
    transform: scale(1.06);
    opacity: 0.72;
  }
}
@media (max-width: 900px) {
  .workflow-strip {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
@media (max-width: 700px) {
  .task-context {
    align-items: flex-start;
  }
  .task-context h1 {
    max-width: 66vw;
  }
  .workflow-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .progress-layout {
    grid-template-columns: 1fr;
  }
  .progress-panel {
    padding: 18px;
  }
  .current-status {
    min-height: 250px;
    padding: 34px 18px;
  }
}
</style>
