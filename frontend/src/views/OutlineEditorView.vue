<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useQuery, useQueryClient } from "@tanstack/vue-query";
import { RouterLink, useRoute, useRouter } from "vue-router";
import { getTask } from "../api/tasks";
import { confirmOutline, getOutline, updateOutline } from "../api/workflows";
import { apiErrorMessage } from "../api/client";
import { resolveTaskRoute } from "../domain/task-routing";
import ChatAssistantDrawer from "../components/chat/ChatAssistantDrawer.vue";
import type { ChatTarget } from "../types/chat";
import type { Outline, OutlineSection } from "../types/workflow";

const route = useRoute();
const router = useRouter();
const taskId = String(route.params.taskId);
const queryClient = useQueryClient();
const taskQuery = useQuery({
  queryKey: ["task", taskId],
  queryFn: () => getTask(taskId),
  refetchInterval: (query) =>
    query.state.data?.status === "RUNNING" ? 1500 : false,
});
const outlineQuery = useQuery({
  queryKey: ["outline", taskId],
  queryFn: () => getOutline(taskId),
});
const outline = ref<Outline>();
const savedOutline = ref("");
const saving = ref(false);
const errorMessage = ref("");
const chatOpen = ref(false);
const chatTarget = ref<ChatTarget | null>(null);
const task = computed(() => taskQuery.data.value);
const targetPageCount = computed(
  () =>
    task.value?.structured_requirement?.target_page_count ??
    task.value?.raw_requirement.target_page_count ??
    0,
);
const allocatedPages = computed(
  () =>
    outline.value?.sections.reduce(
      (total, section) => total + section.page_count,
      0,
    ) ?? 0,
);
const sectionsValid = computed(
  () =>
    Boolean(outline.value?.sections.length) &&
    outline.value!.sections.every(
      (section) =>
        section.items.length > 0 &&
        section.page_count ===
          section.items.reduce((total, item) => total + item.page_count, 0),
    ),
);
const pageAllocationValid = computed(
  () => allocatedPages.value === targetPageCount.value && sectionsValid.value,
);
const isDirty = computed(() =>
  outline.value ? JSON.stringify(outline.value) !== savedOutline.value : false,
);
const isWaiting = computed(
  () => task.value?.status === "WAITING_OUTLINE_CONFIRMATION",
);

function cloneOutline(value: Outline): Outline {
  return JSON.parse(JSON.stringify(value)) as Outline;
}

function createId(): string {
  return `outline-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function openChat(target: ChatTarget | null = null): void {
  chatTarget.value = target;
  chatOpen.value = true;
}

function itemOrdinal(sectionIndex: number, itemIndex: number): number {
  return (
    (outline.value?.sections
      .slice(0, sectionIndex)
      .reduce((count, section) => count + section.items.length, 0) ?? 0) +
    itemIndex +
    1
  );
}

function refreshAfterChatChange(): void {
  for (const key of ["task", "outline", "slides", "revisions", "evaluation"]) {
    void queryClient.invalidateQueries({ queryKey: [key, taskId] });
  }
}

watch(
  () => outlineQuery.data.value?.outline,
  (value) => {
    if (!value) return;
    outline.value = cloneOutline(value);
    savedOutline.value = JSON.stringify(value);
  },
  { immediate: true },
);

watch(
  () => task.value,
  (value) => {
    if (!value) return;
    const destination = resolveTaskRoute(value);
    if (route.path !== destination) void router.replace(destination);
  },
  { immediate: true },
);

function moveSection(index: number, direction: -1 | 1): void {
  const sections = outline.value?.sections;
  if (!sections) return;
  const nextIndex = index + direction;
  if (nextIndex < 0 || nextIndex >= sections.length) return;
  const current = sections[index];
  const next = sections[nextIndex];
  if (!current || !next) return;
  sections[index] = next;
  sections[nextIndex] = current;
}

function addSection(): void {
  if (!outline.value) return;
  const id = createId();
  outline.value.sections.push({
    id,
    title: "新章节",
    objective: "说明本章节的目标",
    page_count: 1,
    items: [
      { id: createId(), title: "新条目", objective: "说明要点", page_count: 1 },
    ],
  });
}

function addItem(section: OutlineSection): void {
  section.items.push({
    id: createId(),
    title: "新条目",
    objective: "说明要点",
    page_count: 1,
  });
  section.page_count += 1;
}

function removeSection(index: number): void {
  outline.value?.sections.splice(index, 1);
}

function removeItem(section: OutlineSection, index: number): void {
  if (section.items.length <= 1) return;
  const removed = section.items[index];
  if (!removed) return;
  section.items.splice(index, 1);
  section.page_count = Math.max(1, section.page_count - removed.page_count);
}

function totalItemPages(section: OutlineSection): number {
  return section.items.reduce((total, item) => total + item.page_count, 0);
}

async function persistOutline(): Promise<number | undefined> {
  if (!task.value || !outline.value || !pageAllocationValid.value)
    return undefined;
  const saved = await updateOutline(taskId, task.value.version, outline.value);
  outline.value = cloneOutline(saved.outline ?? outline.value);
  savedOutline.value = JSON.stringify(outline.value);
  await taskQuery.refetch();
  await outlineQuery.refetch();
  return saved.version;
}

async function save(): Promise<void> {
  if (!isDirty.value) return;
  saving.value = true;
  errorMessage.value = "";
  try {
    await persistOutline();
  } catch (error) {
    errorMessage.value = apiErrorMessage(
      error,
      "保存大纲失败，请检查服务状态后重试。",
    );
  } finally {
    saving.value = false;
  }
}

async function confirm(): Promise<void> {
  if (!task.value || !outline.value || !pageAllocationValid.value) return;
  saving.value = true;
  errorMessage.value = "";
  try {
    const version = isDirty.value ? await persistOutline() : task.value.version;
    if (version === undefined) return;
    await confirmOutline(taskId, version);
    await taskQuery.refetch();
  } catch (error) {
    errorMessage.value = apiErrorMessage(
      error,
      "确认大纲失败，请检查服务状态后重试。",
    );
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <main class="outline-page" aria-labelledby="page-title">
    <header class="page-heading">
      <div>
        <RouterLink class="back-link" :to="`/tasks/${taskId}/requirement`"
          >← 上一步</RouterLink
        >
        <p class="eyebrow">大纲规划</p>
        <h1 id="page-title">检查并编辑大纲</h1>
        <p class="page-intro">
          调整章节、条目和页数分配；总页数必须与需求一致。
        </p>
      </div>
      <div class="page-heading__tools">
        <span v-if="task" class="version-note">版本 {{ task.version }}</span>
        <button
          class="button button--secondary"
          type="button"
          @click="openChat()"
        >
          打开聊天助手
        </button>
      </div>
    </header>

    <div class="workflow-steps" aria-label="工作流进度">
      <span class="workflow-step workflow-step--done">1. 需求解析</span>
      <span class="workflow-step workflow-step--active">2. 大纲规划</span>
      <span class="workflow-step">3. 内容生成</span>
    </div>

    <div
      v-if="taskQuery.isPending.value || outlineQuery.isPending.value"
      class="form-surface"
      role="status"
    >
      正在读取大纲…
    </div>
    <div
      v-else-if="task?.status === 'RUNNING'"
      class="form-surface waiting-panel"
      role="status"
    >
      <span class="loading-mark" aria-hidden="true"></span>
      <h2>正在规划大纲</h2>
      <p>大纲准备好后会显示在这里。</p>
    </div>
    <section
      v-else-if="
        task?.status === 'READY' && task.current_stage === 'outline_confirmed'
      "
      class="form-surface waiting-panel"
      role="status"
    >
      <h2>大纲已确认</h2>
      <p>需求与大纲已保存，后续内容生成可从任务中心继续。</p>
      <RouterLink class="button button--primary" to="/tasks"
        >返回任务中心</RouterLink
      >
    </section>
    <section v-else-if="outline" class="outline-workspace">
      <div v-if="errorMessage" class="page-alert" role="alert">
        {{ errorMessage }}
      </div>
      <div
        class="allocation-banner"
        :class="{ 'allocation-banner--invalid': !pageAllocationValid }"
        role="status"
      >
        <div>
          <strong
            >已分配 {{ allocatedPages }} / {{ targetPageCount }} 页</strong
          >
          <small v-if="!sectionsValid"
            >每个章节的页数必须等于其条目页数之和。</small
          >
          <small v-else-if="allocatedPages !== targetPageCount"
            >请调整章节页数以符合目标页数。</small
          >
          <small v-else>页数分配符合目标。</small>
        </div>
        <span>{{ pageAllocationValid ? "分配有效" : "需调整" }}</span>
      </div>

      <div class="form-surface outline-card">
        <label class="field" for="outline-title"
          ><span>大纲标题</span>
          <input id="outline-title" v-model="outline.title" maxlength="200" />
        </label>
        <article
          v-for="(section, index) in outline.sections"
          :key="section.id"
          class="section-card"
        >
          <div class="section-card__heading">
            <span class="section-index">{{
              String(index + 1).padStart(2, "0")
            }}</span>
            <label
              class="field section-title"
              :for="`section-title-${section.id}`"
              ><span>章节标题</span>
              <input
                :id="`section-title-${section.id}`"
                v-model="section.title"
                maxlength="200"
              />
            </label>
            <div class="section-tools">
              <button
                class="icon-button"
                type="button"
                :disabled="index === 0"
                :aria-label="`上移章节 ${section.title}`"
                @click="moveSection(index, -1)"
              >
                ↑
              </button>
              <button
                class="icon-button"
                type="button"
                :disabled="index === outline!.sections.length - 1"
                :aria-label="`下移章节 ${section.title}`"
                @click="moveSection(index, 1)"
              >
                ↓
              </button>
              <button
                class="text-button text-button--danger"
                type="button"
                :aria-label="`删除章节 ${section.title}`"
                @click="removeSection(index)"
              >
                删除
              </button>
            </div>
          </div>
          <label class="field" :for="`section-objective-${section.id}`"
            ><span>章节目标</span>
            <textarea
              :id="`section-objective-${section.id}`"
              v-model="section.objective"
              rows="2"
              maxlength="1000"
            />
          </label>
          <div class="section-allocation">
            <label class="field" :for="`section-pages-${section.id}`"
              ><span>章节页数</span>
              <input
                :id="`section-pages-${section.id}`"
                v-model.number="section.page_count"
                type="number"
                min="1"
                max="50"
              />
            </label>
            <span>条目合计 {{ totalItemPages(section) }} 页</span>
          </div>
          <div class="items-heading">
            <h3>内容条目</h3>
            <button class="text-button" type="button" @click="addItem(section)">
              添加条目
            </button>
          </div>
          <div
            v-for="(item, itemIndex) in section.items"
            :key="item.id"
            class="item-row"
          >
            <label class="field" :for="`item-title-${item.id}`"
              ><span>条目标题</span>
              <input
                :id="`item-title-${item.id}`"
                v-model="item.title"
                maxlength="200"
              />
            </label>
            <label class="field" :for="`item-objective-${item.id}`"
              ><span>内容目标</span>
              <input
                :id="`item-objective-${item.id}`"
                v-model="item.objective"
                maxlength="1000"
              />
            </label>
            <label class="field item-pages" :for="`item-pages-${item.id}`"
              ><span>页数</span>
              <input
                :id="`item-pages-${item.id}`"
                v-model.number="item.page_count"
                type="number"
                min="1"
                max="50"
              />
            </label>
            <button
              class="text-button item-chat"
              type="button"
              @click="
                openChat({
                  target_type: 'outline_item',
                  target_id: item.id,
                  label: `第 ${itemOrdinal(index, itemIndex)} 点 · ${item.title}`,
                })
              "
            >
              让助手修改
            </button>
            <button
              class="text-button text-button--danger item-remove"
              type="button"
              :disabled="section.items.length <= 1"
              :aria-label="`删除条目 ${item.title}`"
              @click="removeItem(section, itemIndex)"
            >
              删除
            </button>
          </div>
        </article>
        <button
          class="button button--secondary add-section"
          type="button"
          @click="addSection"
        >
          ＋ 添加章节
        </button>
      </div>

      <footer class="form-actions">
        <RouterLink
          class="button button--secondary"
          :to="`/tasks/${taskId}/requirement`"
          >上一步</RouterLink
        >
        <div class="actions-right">
          <span class="save-state" role="status">{{
            saving ? "保存中…" : isDirty ? "未保存" : "已保存"
          }}</span>
          <button
            class="button button--secondary"
            type="button"
            :disabled="saving || !isDirty || !pageAllocationValid"
            @click="save"
          >
            保存大纲
          </button>
          <button
            class="button button--primary"
            type="button"
            :disabled="saving || !isWaiting || !pageAllocationValid"
            @click="confirm"
          >
            {{ saving ? "正在确认…" : "确认大纲并开始生成" }}
          </button>
        </div>
      </footer>
    </section>
    <div v-else class="page-alert" role="alert">
      尚无可审核的大纲，请返回需求页继续处理。
    </div>
    <ChatAssistantDrawer
      v-if="task"
      :task-id="taskId"
      :task-version="task.version"
      :open="chatOpen"
      :target="chatTarget"
      @close="chatOpen = false"
      @updated="refreshAfterChatChange"
    />
  </main>
</template>

<style scoped>
.outline-page {
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
.page-heading__tools {
  display: flex;
  align-items: center;
  gap: 10px;
}
.button {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  justify-content: center;
  padding: 0 13px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  background: white;
  color: var(--color-text-strong);
  font: inherit;
  font-weight: 650;
  cursor: pointer;
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
.workflow-step--active,
.workflow-step--done {
  background: var(--color-primary-100);
  color: var(--color-primary-800);
  font-weight: 700;
}
.form-surface {
  padding: 22px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
  box-shadow: var(--shadow-panel);
}
.outline-workspace {
  display: grid;
  gap: 14px;
}
.allocation-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 18px;
  padding: 16px 20px;
  border: 1px solid #a9dfc8;
  border-radius: 10px;
  background: var(--color-success-bg);
  color: #086b43;
}
.allocation-banner--invalid {
  border-color: #f2d18f;
  background: var(--color-warning-bg);
  color: #855100;
}
.allocation-banner div {
  display: grid;
  gap: 4px;
}
.allocation-banner small {
  color: inherit;
}
.allocation-banner > span {
  font-size: 0.9rem;
  font-weight: 700;
}
.outline-card {
  display: grid;
  gap: 18px;
}
.field {
  display: grid;
  gap: 6px;
  color: var(--color-text-strong);
  font-weight: 650;
}
.field input,
.field textarea {
  box-sizing: border-box;
  width: 100%;
  padding: 10px 11px;
  border: 1px solid var(--color-border-strong);
  border-radius: 6px;
  background: white;
  color: var(--color-text-strong);
  font: inherit;
  font-weight: 450;
}
.section-card {
  display: grid;
  gap: 14px;
  padding: 18px;
  border: 1px solid var(--color-border);
  border-radius: 10px;
  background: var(--color-surface-muted);
}
.section-card__heading {
  display: flex;
  align-items: flex-end;
  gap: 12px;
}
.section-index {
  padding: 9px 10px;
  border-radius: 8px;
  background: var(--color-primary-100);
  color: var(--color-primary-700);
  font-weight: 800;
}
.section-title {
  flex: 1;
}
.section-tools {
  display: flex;
  align-items: center;
  gap: 6px;
}
.icon-button {
  width: 34px;
  height: 34px;
  border: 1px solid var(--color-border-strong);
  border-radius: 6px;
  background: white;
  color: var(--color-text);
  cursor: pointer;
}
.icon-button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.section-allocation {
  display: flex;
  align-items: flex-end;
  gap: 14px;
}
.section-allocation .field {
  width: 130px;
}
.section-allocation > span {
  padding: 10px 0;
  color: var(--color-text-muted);
  font-size: 0.9rem;
}
.items-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 10px;
  border-top: 1px solid var(--color-border);
}
.items-heading h3 {
  margin: 0;
  color: var(--color-text-strong);
  font-size: 1rem;
}
.item-row {
  display: grid;
  grid-template-columns: 1.1fr 1.4fr 90px auto auto;
  align-items: end;
  gap: 10px;
}
.item-pages {
  width: 90px;
}
.text-button {
  padding: 6px 4px;
  border: 0;
  background: transparent;
  color: var(--color-primary-700);
  font: inherit;
  font-weight: 650;
  cursor: pointer;
}
.text-button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.text-button--danger {
  color: #b42d41;
}
.add-section {
  justify-self: start;
}
.form-actions {
  position: sticky;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 0 4px;
  background: var(--color-page-bg);
}
.actions-right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.save-state {
  color: var(--color-text-muted);
  font-size: 0.88rem;
}
.button {
  display: inline-flex;
  min-height: 42px;
  align-items: center;
  justify-content: center;
  padding: 0 15px;
  border: 1px solid transparent;
  border-radius: 7px;
  font: inherit;
  font-weight: 650;
  text-decoration: none;
  cursor: pointer;
  white-space: nowrap;
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
  opacity: 0.5;
  cursor: not-allowed;
}
.waiting-panel {
  display: grid;
  justify-items: center;
  gap: 10px;
  padding: 60px 24px;
  text-align: center;
}
.waiting-panel h2 {
  margin: 0;
  color: var(--color-text-strong);
}
.waiting-panel p {
  color: var(--color-text-muted);
}
.page-alert {
  padding: 12px 14px;
  border-radius: 8px;
  background: var(--color-danger-bg);
  color: #a61f35;
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
  .page-heading {
    align-items: flex-start;
  }
  .page-heading__tools {
    align-items: flex-end;
    flex-direction: column;
  }
  .form-surface {
    padding: 16px;
  }
  .section-card__heading {
    flex-wrap: wrap;
  }
  .section-title {
    min-width: calc(100% - 60px);
  }
  .section-tools {
    margin-left: auto;
  }
  .item-row {
    grid-template-columns: 1fr 1fr;
  }
  .item-pages {
    width: auto;
  }
  .item-remove {
    justify-self: start;
  }
  .item-chat {
    justify-self: start;
  }
  .form-actions,
  .actions-right {
    align-items: stretch;
    flex-direction: column;
  }
  .form-actions .button {
    width: 100%;
  }
  .save-state {
    text-align: right;
  }
}
</style>
