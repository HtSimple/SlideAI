<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { RouterLink, useRoute, useRouter } from "vue-router";
import { getTask } from "../api/tasks";
import {
  confirmRequirement,
  getRequirement,
  updateRequirement,
} from "../api/workflows";
import { apiErrorMessage } from "../api/client";
import type { StructuredRequirement } from "../types/workflow";

const route = useRoute();
const router = useRouter();
const taskId = String(route.params.taskId);
const taskQuery = useQuery({
  queryKey: ["task", taskId],
  queryFn: () => getTask(taskId),
  refetchInterval: (query) =>
    query.state.data?.status === "RUNNING" ? 1500 : false,
});
const requirementQuery = useQuery({
  queryKey: ["requirement", taskId],
  queryFn: () => getRequirement(taskId),
  refetchInterval: () =>
    taskQuery.data.value?.status === "RUNNING" ? 1500 : false,
});
const form = ref<StructuredRequirement>();
const saving = ref(false);
const errorMessage = ref("");
const task = computed(() => taskQuery.data.value);
const missingFields = computed(() => {
  const value = form.value;
  if (!value) return [];
  const missing: string[] = [];
  if (!value.topic?.trim()) missing.push("topic");
  if (
    !value.target_page_count ||
    value.target_page_count < 3 ||
    value.target_page_count > 50
  )
    missing.push("target_page_count");
  if (!value.scenario?.trim()) missing.push("scenario");
  if (!value.audience?.trim()) missing.push("audience");
  if (!value.style?.trim()) missing.push("style");
  return missing;
});
const fieldLabels: Record<string, string> = {
  topic: "主题",
  target_page_count: "目标页数",
  scenario: "使用场景",
  audience: "目标受众",
  style: "内容风格",
};

watch(
  () => requirementQuery.data.value?.structured_requirement,
  (value) => {
    if (!value) return;
    form.value = {
      ...value,
      constraints: [...value.constraints],
    };
  },
  { immediate: true },
);

watch(
  () => task.value?.status,
  (status) => {
    if (status === "WAITING_OUTLINE_CONFIRMATION") {
      void router.replace(`/tasks/${taskId}/outline`);
    }
  },
);

function requirementsPayload(): StructuredRequirement {
  const value = form.value!;
  return {
    ...value,
    topic: value.topic?.trim() || null,
    scenario: value.scenario?.trim() || null,
    audience: value.audience?.trim() || null,
    style: value.style?.trim() || null,
    constraints: value.constraints.map((item) => item.trim()).filter(Boolean),
  };
}

async function saveAndContinue(): Promise<void> {
  if (!task.value || !form.value || missingFields.value.length) return;
  saving.value = true;
  errorMessage.value = "";
  try {
    const saved = await updateRequirement(
      taskId,
      task.value.version,
      requirementsPayload(),
    );
    await confirmRequirement(taskId, saved.version);
    await taskQuery.refetch();
    await requirementQuery.refetch();
  } catch (error) {
    errorMessage.value = apiErrorMessage(
      error,
      "保存需求失败，请检查服务状态后重试。",
    );
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <main class="review-page" aria-labelledby="page-title">
    <header class="page-heading">
      <div>
        <RouterLink class="back-link" :to="`/tasks/${taskId}/edit`"
          >← 上一步</RouterLink
        >
        <p class="eyebrow">需求解析</p>
        <h1 id="page-title">确认内容需求</h1>
        <p class="page-intro">
          检查解析结果，补足系统无法从原始描述中确定的信息。
        </p>
      </div>
      <span v-if="task" class="version-note">版本 {{ task.version }}</span>
    </header>

    <div class="workflow-steps" aria-label="工作流进度">
      <span class="workflow-step workflow-step--active">1. 需求解析</span>
      <span class="workflow-step">2. 大纲规划</span>
      <span class="workflow-step">3. 内容生成</span>
    </div>

    <div
      v-if="taskQuery.isPending.value || requirementQuery.isPending.value"
      class="form-surface"
      role="status"
    >
      正在读取需求…
    </div>
    <div
      v-else-if="task?.status === 'RUNNING'"
      class="form-surface waiting-panel"
      role="status"
    >
      <span class="loading-mark" aria-hidden="true"></span>
      <h2>正在分析需求</h2>
      <p>确认请求已提交。大纲准备好后会自动进入大纲审核。</p>
    </div>
    <form
      v-else-if="form"
      class="review-layout"
      @submit.prevent="saveAndContinue"
    >
      <section class="form-surface requirement-form" aria-label="结构化需求">
        <div class="section-heading">
          <span class="section-number">01</span>
          <div>
            <h2>结构化需求</h2>
            <p>系统不确定的字段会留空，由您确认。</p>
          </div>
        </div>
        <div v-if="errorMessage" class="page-alert" role="alert">
          {{ errorMessage }}
        </div>
        <label class="field" for="requirement-topic"
          ><span>主题 <b>*</b></span>
          <input
            id="requirement-topic"
            v-model="form.topic"
            maxlength="200"
            required
          />
        </label>
        <label class="field" for="requirement-pages"
          ><span>目标页数 <b>*</b></span>
          <div class="number-input">
            <input
              id="requirement-pages"
              v-model.number="form.target_page_count"
              type="number"
              min="3"
              max="50"
              required
            /><span>页</span>
          </div>
        </label>
        <label class="field" for="requirement-scenario"
          ><span>使用场景 <b>*</b></span>
          <input
            id="requirement-scenario"
            v-model="form.scenario"
            maxlength="500"
            required
          />
        </label>
        <label class="field" for="requirement-audience"
          ><span>目标受众 <b>*</b></span>
          <input
            id="requirement-audience"
            v-model="form.audience"
            maxlength="500"
            required
          />
        </label>
        <label class="field" for="requirement-style"
          ><span>内容风格 <b>*</b></span>
          <input
            id="requirement-style"
            v-model="form.style"
            maxlength="200"
            required
          />
        </label>
        <label class="field" for="requirement-language"
          ><span>语言</span>
          <input
            id="requirement-language"
            v-model="form.language"
            maxlength="20"
          />
        </label>
        <label class="field" for="requirement-constraints"
          ><span>特殊限制</span>
          <textarea
            id="requirement-constraints"
            :value="form.constraints.join('\n')"
            rows="3"
            @input="
              form.constraints = ($event.target as HTMLTextAreaElement).value
                .split('\n')
                .filter(Boolean)
            "
          />
        </label>
        <details v-if="form.original_text" class="source-description">
          <summary>查看原始描述</summary>
          <p>{{ form.original_text }}</p>
        </details>
      </section>

      <aside
        class="form-surface confirmation-panel"
        aria-labelledby="confirmation-title"
      >
        <div class="section-heading">
          <span class="section-number section-number--muted">02</span>
          <div>
            <h2 id="confirmation-title">
              需要您确认 {{ missingFields.length }} 项
            </h2>
            <p>补全必填信息后即可继续。</p>
          </div>
        </div>
        <ul v-if="missingFields.length" class="missing-list">
          <li v-for="field in missingFields" :key="field">
            {{ fieldLabels[field] }}
          </li>
        </ul>
        <p v-else class="complete-note">所有必填信息已填写，可以生成大纲。</p>
        <div class="model-summary">
          <span>模型策略</span
          ><strong>{{
            task?.model_preference.mode === "auto" ? "自动选择" : "手动选择"
          }}</strong>
          <small
            >初始复杂度：{{ task?.complexity.tier }} ·
            {{ task?.complexity.total_score }}/10</small
          >
        </div>
      </aside>

      <footer class="form-actions">
        <RouterLink
          class="button button--secondary"
          :to="`/tasks/${taskId}/edit`"
          >上一步</RouterLink
        >
        <button
          class="button button--primary"
          type="submit"
          :disabled="saving || missingFields.length > 0"
        >
          {{ saving ? "正在保存…" : "确认需求并生成大纲" }}
        </button>
      </footer>
    </form>
    <div v-else class="page-alert" role="alert">
      需求解析结果不可用，请返回任务设置后重试。
    </div>
  </main>
</template>

<style scoped>
.review-page {
  max-width: 1180px;
  margin: 0 auto;
}
.page-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 20px;
}
.back-link {
  color: var(--color-primary-700);
  text-decoration: none;
  font-weight: 650;
}
.eyebrow {
  margin: 16px 0 6px;
  color: var(--color-primary-700);
  font-size: 0.85rem;
  font-weight: 700;
}
h1 {
  margin: 0;
  color: var(--color-text-strong);
  font-size: clamp(1.7rem, 4vw, 2.3rem);
}
.page-intro {
  margin: 8px 0 0;
  color: var(--color-text-muted);
}
.version-note {
  color: var(--color-text-muted);
  font-size: 0.9rem;
}
.workflow-steps {
  display: flex;
  gap: 10px;
  overflow-x: auto;
  margin: 0 0 20px;
}
.workflow-step {
  flex: 1;
  min-width: 130px;
  padding: 12px 14px;
  border-radius: 8px;
  background: var(--color-surface);
  color: var(--color-text-muted);
  text-align: center;
}
.workflow-step--active {
  background: var(--color-primary-100);
  color: var(--color-primary-800);
  font-weight: 700;
}
.form-surface {
  padding: 24px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
  box-shadow: var(--shadow-panel);
}
.review-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(260px, 0.8fr);
  gap: 18px;
}
.requirement-form,
.confirmation-panel {
  display: grid;
  align-content: start;
  gap: 18px;
}
.section-heading {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.section-heading h2 {
  margin: 0;
  color: var(--color-text-strong);
  font-size: 1.1rem;
}
.section-heading p {
  margin: 4px 0 0;
  color: var(--color-text-muted);
  font-size: 0.9rem;
}
.section-number {
  display: grid;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  place-items: center;
  border-radius: 9px;
  background: var(--color-primary-100);
  color: var(--color-primary-700);
  font-weight: 750;
}
.section-number--muted {
  background: var(--color-surface-muted);
  color: var(--color-text-muted);
}
.field {
  display: grid;
  gap: 7px;
  color: var(--color-text-strong);
  font-weight: 650;
}
.field b {
  color: var(--color-danger);
}
.field input,
.field textarea,
.number-input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  background: white;
  color: var(--color-text-strong);
  font: inherit;
}
.field input,
.field textarea {
  padding: 11px 12px;
}
.number-input {
  display: flex;
  align-items: center;
  padding-right: 12px;
}
.number-input input {
  border: 0;
  outline: none;
}
.number-input span {
  color: var(--color-text-muted);
  font-weight: 500;
}
.missing-list {
  display: grid;
  gap: 8px;
  padding-left: 20px;
  color: #9a5a00;
}
.complete-note {
  padding: 12px;
  border-radius: 8px;
  background: var(--color-success-bg);
  color: #086b43;
}
.model-summary {
  display: grid;
  gap: 6px;
  padding-top: 18px;
  border-top: 1px solid var(--color-border);
  color: var(--color-text-muted);
}
.model-summary strong {
  color: var(--color-text-strong);
}
.source-description {
  padding-top: 8px;
  border-top: 1px solid var(--color-border);
  color: var(--color-text-muted);
}
.source-description summary {
  cursor: pointer;
  color: var(--color-primary-700);
  font-weight: 650;
}
.form-actions {
  grid-column: 1 / -1;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  position: sticky;
  bottom: 0;
  padding: 14px 0 4px;
  background: var(--color-page-bg);
}
.button {
  display: inline-flex;
  min-height: 42px;
  align-items: center;
  justify-content: center;
  padding: 0 16px;
  border: 1px solid transparent;
  border-radius: 7px;
  font: inherit;
  font-weight: 650;
  text-decoration: none;
  cursor: pointer;
}
.button--primary {
  background: var(--color-primary-600);
  color: white;
}
.button--secondary {
  border-color: var(--color-border-strong);
  background: white;
  color: var(--color-text-strong);
}
.button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.page-alert {
  padding: 12px 14px;
  border-radius: 8px;
  background: var(--color-danger-bg);
  color: #a61f35;
}
.waiting-panel {
  display: grid;
  justify-items: center;
  padding: 64px 24px;
  text-align: center;
}
.waiting-panel h2 {
  margin-bottom: 0;
  color: var(--color-text-strong);
}
.waiting-panel p {
  color: var(--color-text-muted);
}
.loading-mark {
  width: 26px;
  height: 26px;
  border: 3px solid var(--color-primary-100);
  border-top-color: var(--color-primary-600);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@media (max-width: 760px) {
  .review-layout {
    grid-template-columns: 1fr;
  }
  .form-surface {
    padding: 18px;
  }
  .page-heading {
    align-items: flex-start;
  }
}
</style>
