<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { RouterLink, useRoute, useRouter } from "vue-router";
import { createTask, getModels, getTask, patchTask } from "../api/tasks";
import type { CreateTaskInput, TaskRecord } from "../types/tasks";

const route = useRoute();
const router = useRouter();
const taskId = computed(() =>
  typeof route.params.taskId === "string" ? route.params.taskId : undefined,
);
const modelQuery = useQuery({
  queryKey: ["models"],
  queryFn: getModels,
  staleTime: 60000,
});
const taskQuery = useQuery({
  queryKey: computed(() => ["task", taskId.value]),
  queryFn: () => getTask(taskId.value!),
  enabled: computed(() => Boolean(taskId.value)),
});
const topic = ref("");
const pageCount = ref(12);
const scenario = ref("");
const audience = ref("");
const style = ref("");
const constraints = ref("");
const preferenceMode = ref<"auto" | "manual">("auto");
const modelKey = ref("");
const saving = ref(false);
const pageError = ref("");
const fieldError = ref("");
const availableModels = computed(() => modelQuery.data.value ?? []);
const isEdit = computed(() => Boolean(taskId.value));

watch(
  () => taskQuery.data.value,
  (task) => {
    if (task) fillForm(task);
  },
  { immediate: true },
);

function fillForm(task: TaskRecord): void {
  topic.value = task.raw_requirement.topic;
  pageCount.value = task.raw_requirement.target_page_count;
  scenario.value = task.raw_requirement.scenario ?? "";
  audience.value = task.raw_requirement.audience ?? "";
  style.value = task.raw_requirement.style ?? "";
  constraints.value =
    task.raw_requirement.special_constraints?.join("\n") ?? "";
  preferenceMode.value = task.model_preference.mode;
  modelKey.value = task.model_preference.model_key ?? "";
}

function buildInput(): CreateTaskInput {
  return {
    raw_requirement: {
      topic: topic.value.trim(),
      target_page_count: Number(pageCount.value),
      scenario: scenario.value.trim(),
      audience: audience.value.trim(),
      style: style.value.trim(),
      special_constraints: constraints.value
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean),
    },
    model_preference:
      preferenceMode.value === "auto"
        ? { mode: "auto" }
        : { mode: "manual", model_key: modelKey.value },
  };
}

function validate(): boolean {
  if (!topic.value.trim() || topic.value.trim().length > 200) {
    fieldError.value = "请输入 1–200 个字符的主题。";
    return false;
  }
  if (
    !Number.isInteger(Number(pageCount.value)) ||
    Number(pageCount.value) < 3 ||
    Number(pageCount.value) > 50
  ) {
    fieldError.value = "目标页数需在 3–50 页之间。";
    return false;
  }
  if (!scenario.value.trim() || !audience.value.trim() || !style.value.trim()) {
    fieldError.value = "请填写使用场景、目标受众和内容风格。";
    return false;
  }
  if (constraints.value.length > 500) {
    fieldError.value = "特殊限制最多 500 个字符。";
    return false;
  }
  if (preferenceMode.value === "manual" && !modelKey.value) {
    fieldError.value = "请选择一个可用模型，或切换为自动选择。";
    return false;
  }
  fieldError.value = "";
  return true;
}

async function saveTask(): Promise<void> {
  pageError.value = "";
  if (!validate()) return;
  saving.value = true;
  try {
    const input = buildInput();
    if (taskId.value && taskQuery.data.value) {
      await patchTask(taskId.value, taskQuery.data.value.version, input);
    } else {
      await createTask(input);
    }
    await router.push("/tasks");
  } catch {
    pageError.value = "草稿保存失败，请检查服务状态后重试。";
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <section class="task-edit" aria-labelledby="page-title">
    <header class="page-heading">
      <div>
        <RouterLink class="back-link" to="/tasks">← 返回任务中心</RouterLink>
        <p class="eyebrow">{{ isEdit ? "任务设置" : "新建任务" }}</p>
        <h1 id="page-title">{{ isEdit ? "编辑任务" : "准备您的演示文稿" }}</h1>
        <p class="page-intro">
          先描述目标和受众，SlideAI 会据此规划适合的内容结构。
        </p>
      </div>
      <span v-if="isEdit && taskQuery.data.value" class="version-note"
        >草稿 · 版本 {{ taskQuery.data.value.version }}</span
      >
    </header>

    <div v-if="taskQuery.isError.value" class="page-alert" role="alert">
      无法加载该任务，请返回任务中心后重试。
    </div>
    <div
      v-else-if="taskQuery.isPending.value && isEdit"
      class="form-surface"
      role="status"
    >
      正在加载任务…
    </div>
    <form v-else class="editor-grid" @submit.prevent="saveTask">
      <section class="form-surface" aria-label="演示文稿需求">
        <div class="section-heading">
          <span class="section-number">01</span>
          <div>
            <h2>内容需求</h2>
            <p>这些信息将决定内容的范围与表达方式。</p>
          </div>
        </div>
        <div v-if="pageError || fieldError" class="page-alert" role="alert">
          {{ pageError || fieldError }}
        </div>
        <label class="field" for="topic"
          ><span>主题 <b>*</b></span
          ><input
            id="topic"
            v-model="topic"
            maxlength="200"
            required
            placeholder="例如：2026 年生成式 AI 行业趋势"
          /><small>请用一句话说明这份演示文稿要讲什么。</small></label
        >
        <label class="field" for="page-count"
          ><span>目标页数 <b>*</b></span>
          <div class="number-input">
            <input
              id="page-count"
              v-model.number="pageCount"
              type="number"
              min="3"
              max="50"
              required
            /><span>页</span>
          </div>
          <small>可设置 3–50 页，之后还能在大纲中调整结构。</small></label
        >
        <label class="field" for="scenario"
          ><span>使用场景 <b>*</b></span
          ><input
            id="scenario"
            v-model="scenario"
            required
            placeholder="例如：面向管理层的季度战略汇报"
        /></label>
        <label class="field" for="audience"
          ><span>目标受众 <b>*</b></span
          ><input
            id="audience"
            v-model="audience"
            required
            placeholder="例如：业务负责人和部门主管"
        /></label>
        <label class="field" for="style"
          ><span>内容风格 <b>*</b></span
          ><input
            id="style"
            v-model="style"
            required
            placeholder="例如：清晰、务实，以数据和结论为主"
        /></label>
        <label class="field" for="constraints"
          ><span>特殊限制 <em>选填</em></span
          ><textarea
            id="constraints"
            v-model="constraints"
            maxlength="500"
            rows="3"
            placeholder="每行一项，例如：避免使用未经证实的市场规模数据"
          /><small>{{ constraints.length }}/500</small></label
        >
      </section>

      <aside class="side-column">
        <section class="form-surface model-panel" aria-labelledby="model-title">
          <div class="section-heading">
            <span class="section-number">02</span>
            <div>
              <h2 id="model-title">模型选择</h2>
              <p>可自动选择，也可以指定首选模型。</p>
            </div>
          </div>
          <label
            class="model-choice"
            :class="{ 'model-choice--selected': preferenceMode === 'auto' }"
            ><input v-model="preferenceMode" type="radio" value="auto" /><span
              class="model-choice__radio"
            /><span
              ><strong>自动选择</strong
              ><small>根据需求复杂度，为不同环节匹配合适模型。</small></span
            ><b class="model-tier">推荐</b></label
          >
          <label
            v-for="model in availableModels"
            :key="model.key"
            class="model-choice"
            :class="{
              'model-choice--selected':
                preferenceMode === 'manual' && modelKey === model.key,
              'model-choice--disabled': !model.enabled || !model.available,
            }"
            ><input
              v-model="modelKey"
              type="radio"
              :value="model.key"
              :disabled="!model.enabled || !model.available"
              @change="preferenceMode = 'manual'"
            /><span class="model-choice__radio" /><span
              ><strong>{{ model.display_name }}</strong
              ><small>{{
                model.tier === "fast"
                  ? "快速 · 适合轻量任务"
                  : model.tier === "balanced"
                    ? "均衡 · 适合多数业务任务"
                    : "高级 · 适合复杂分析任务"
              }}</small></span
            ><b v-if="!model.available" class="model-unavailable"
              >未配置</b
            ></label
          >
          <p v-if="modelQuery.isError.value" class="inline-error">
            模型目录暂不可用，将保留自动选择。
          </p>
        </section>

        <section
          class="form-surface source-placeholder"
          aria-labelledby="source-title"
        >
          <div class="section-heading">
            <span class="section-number section-number--muted">03</span>
            <div>
              <h2 id="source-title">参考资料</h2>
              <p>支持 PDF、DOCX、Markdown 和 TXT。</p>
            </div>
          </div>
          <div class="upload-placeholder">
            <span aria-hidden="true">↑</span><strong>资料上传即将开放</strong
            ><small>下一阶段将加入资料解析与引用能力。</small>
          </div>
          <small class="limit-note"
            >单文件最多 20 MiB · 每个任务最多 10 个文件</small
          >
        </section>
      </aside>
      <footer class="form-actions">
        <RouterLink class="button button--secondary" to="/tasks"
          >取消</RouterLink
        ><button
          class="button button--primary"
          type="submit"
          :disabled="saving"
        >
          {{ saving ? "正在保存…" : "保存草稿" }}
        </button>
      </footer>
    </form>
  </section>
</template>

<style scoped>
.page-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 24px;
}
.back-link {
  display: inline-block;
  margin-bottom: 19px;
  color: var(--color-primary-700);
  font-size: 13px;
  text-decoration: none;
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
.page-intro {
  margin: 7px 0 0;
  color: var(--color-text-muted);
  font-size: 14px;
}
.version-note {
  color: var(--color-text-muted);
  font-size: 13px;
}
.editor-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.16fr) minmax(320px, 0.84fr);
  gap: 18px;
  align-items: start;
}
.form-surface {
  padding: 22px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
}
.section-heading {
  display: flex;
  align-items: flex-start;
  gap: 13px;
  margin-bottom: 21px;
}
.section-number {
  display: grid;
  width: 30px;
  height: 30px;
  flex: none;
  place-items: center;
  border-radius: 9px;
  background: var(--color-primary-050);
  color: var(--color-primary-700);
  font-size: 12px;
  font-weight: 700;
}
.section-number--muted {
  background: #f1f5f9;
  color: #64748b;
}
.section-heading h2 {
  margin: 0;
  color: var(--color-text-strong);
  font-size: 17px;
}
.section-heading p {
  margin: 5px 0 0;
  color: var(--color-text-muted);
  font-size: 13px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin: 0 0 17px;
  color: var(--color-text-strong);
  font-size: 13px;
  font-weight: 600;
}
.field:last-child {
  margin-bottom: 0;
}
.field b {
  color: #d92d20;
}
.field em {
  margin-left: 6px;
  color: var(--color-text-muted);
  font-size: 11px;
  font-style: normal;
  font-weight: 400;
}
.field input,
.field textarea,
.number-input {
  width: 100%;
  min-height: 42px;
  padding: 0 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: #fff;
  color: var(--color-text-strong);
  font: 400 14px inherit;
}
.field textarea {
  padding: 10px 12px;
  resize: vertical;
}
.field input:focus,
.field textarea:focus,
.number-input:focus-within {
  border-color: var(--color-primary-600);
  outline: 3px solid
    color-mix(in srgb, var(--color-primary-600) 16%, transparent);
}
.field small {
  color: var(--color-text-muted);
  font-size: 11px;
  font-weight: 400;
}
.number-input {
  display: flex;
  align-items: center;
  padding-right: 12px;
}
.number-input input {
  min-height: 40px;
  border: 0;
  outline: none !important;
}
.number-input span {
  color: var(--color-text-muted);
  font-weight: 400;
}
.side-column {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.model-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.model-choice {
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 70px;
  padding: 13px;
  border: 1px solid var(--color-border);
  border-radius: 12px;
  cursor: pointer;
}
.model-choice--selected {
  border-color: var(--color-primary-600);
  background: #f7faff;
}
.model-choice--disabled {
  opacity: 0.57;
  cursor: not-allowed;
}
.model-choice input {
  position: absolute;
  opacity: 0;
}
.model-choice__radio {
  display: grid;
  width: 18px;
  height: 18px;
  flex: none;
  place-items: center;
  border: 1.5px solid #98a2b3;
  border-radius: 50%;
}
.model-choice input:checked + .model-choice__radio {
  border-color: var(--color-primary-600);
}
.model-choice input:checked + .model-choice__radio:after {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--color-primary-600);
  content: "";
}
.model-choice input:focus-visible + .model-choice__radio {
  outline: 3px solid var(--color-focus);
  outline-offset: 2px;
}
.model-choice strong,
.model-choice small {
  display: block;
}
.model-choice strong {
  color: var(--color-text-strong);
  font-size: 13px;
}
.model-choice small {
  margin-top: 4px;
  color: var(--color-text-muted);
  font-size: 11px;
  line-height: 1.4;
}
.model-tier,
.model-unavailable {
  margin-left: auto;
  color: var(--color-primary-700);
  font-size: 10px;
  font-weight: 600;
}
.model-unavailable {
  color: #667085;
}
.source-placeholder {
  min-height: 220px;
}
.upload-placeholder {
  display: flex;
  min-height: 114px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: 1px dashed #cbd5e1;
  border-radius: 12px;
  background: #fbfcfe;
  text-align: center;
}
.upload-placeholder > span {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border-radius: 8px;
  background: #eef4ff;
  color: var(--color-primary-700);
  font-size: 19px;
}
.upload-placeholder strong {
  color: var(--color-text-strong);
  font-size: 12px;
}
.upload-placeholder small,
.limit-note {
  color: var(--color-text-muted);
  font-size: 11px;
}
.limit-note {
  display: block;
  margin-top: 11px;
}
.form-actions {
  grid-column: 1/-1;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 2px;
}
.button {
  display: inline-flex;
  min-height: 42px;
  align-items: center;
  justify-content: center;
  padding: 0 17px;
  border: 1px solid var(--color-primary-600);
  border-radius: var(--radius-control);
  font: 600 14px inherit;
  text-decoration: none;
  cursor: pointer;
}
.button:focus-visible {
  outline: 3px solid var(--color-focus);
  outline-offset: 2px;
}
.button:disabled {
  opacity: 0.6;
  cursor: wait;
}
.button--primary {
  background: var(--color-primary-600);
  color: white;
}
.button--secondary {
  background: white;
  color: var(--color-primary-700);
}
.page-alert,
.inline-error {
  margin: 0 0 16px;
  padding: 11px 13px;
  border: 1px solid #fecdca;
  border-radius: 10px;
  background: #fff6f5;
  color: #b42318;
  font-size: 13px;
}
.inline-error {
  margin: 0;
}
.page-alert[role="alert"]:empty {
  display: none;
}
@media (max-width: 850px) {
  .editor-grid {
    grid-template-columns: 1fr;
  }
  .side-column {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }
  .form-actions {
    grid-column: 1;
  }
}
@media (max-width: 620px) {
  .page-heading {
    align-items: flex-start;
    flex-direction: column;
  }
  .form-surface {
    padding: 17px;
  }
  .side-column {
    display: flex;
  }
  .form-actions {
    position: sticky;
    bottom: 0;
    z-index: 2;
    justify-content: stretch;
    padding: 12px;
    background: var(--color-page-bg);
  }
  .form-actions > * {
    flex: 1;
  }
}
</style>
