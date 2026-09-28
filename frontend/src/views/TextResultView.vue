<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useQuery, useQueryClient } from "@tanstack/vue-query";
import { RouterLink, useRoute, useRouter } from "vue-router";
import { apiErrorMessage } from "../api/client";
import { downloadMarkdown, getMarkdown, getSlides } from "../api/content";
import { getTask } from "../api/tasks";
import { getRevisions } from "../api/evaluation";
import { undoChatRevision } from "../api/chat";
import ChatAssistantDrawer from "../components/chat/ChatAssistantDrawer.vue";
import EvaluationPanel from "../components/result/EvaluationPanel.vue";
import { resolveTaskRoute } from "../domain/task-routing";
import type { SlideContent } from "../types/content";
import type { ChatTarget } from "../types/chat";

type ResultTab = "content" | "evaluation" | "markdown" | "history";
const route = useRoute();
const router = useRouter();
const queryClient = useQueryClient();
const taskId = String(route.params.taskId);
const taskQuery = useQuery({
  queryKey: ["task", taskId],
  queryFn: () => getTask(taskId),
});
const completed = computed(() => taskQuery.data.value?.status === "COMPLETED");
const slidesQuery = useQuery({
  queryKey: ["slides", taskId],
  queryFn: () => getSlides(taskId),
  enabled: completed,
});
const markdownQuery = useQuery({
  queryKey: ["markdown", taskId],
  queryFn: () => getMarkdown(taskId),
  enabled: completed,
});
const task = computed(() => taskQuery.data.value);
const slides = computed(() => slidesQuery.data.value?.items ?? []);
const validTabs: ResultTab[] = ["content", "evaluation", "markdown", "history"];
const tab = computed<ResultTab>(() => {
  const value = Array.isArray(route.query.tab)
    ? route.query.tab[0]
    : route.query.tab;
  return validTabs.includes(value as ResultTab)
    ? (value as ResultTab)
    : "content";
});
const revisionsQuery = useQuery({
  queryKey: ["revisions", taskId],
  queryFn: () => getRevisions(taskId),
  enabled: computed(() => tab.value === "history"),
});
const chatOpen = ref(false);
const pageParam = computed(() =>
  Array.isArray(route.query.page) ? route.query.page[0] : route.query.page,
);
const selectedPageNumber = computed(() => Number(pageParam.value));
const selectedSlide = computed<SlideContent | undefined>(
  () =>
    slides.value.find(
      (slide) => slide.page_number === selectedPageNumber.value,
    ) ?? slides.value[0],
);
const chatTarget = computed<ChatTarget | null>(() =>
  selectedSlide.value
    ? {
        target_type: "slide",
        target_id: selectedSlide.value.id,
        label: `第 ${selectedSlide.value.page_number} 页`,
      }
    : null,
);
const sections = computed(() => {
  const grouped = new Map<string, SlideContent[]>();
  for (const slide of slides.value) {
    const items = grouped.get(slide.section_id) ?? [];
    items.push(slide);
    grouped.set(slide.section_id, items);
  }
  const outlineSections = task.value?.outline?.sections ?? [];
  return [...grouped.entries()].map(([id, items]) => ({
    id,
    title:
      outlineSections.find((section) => section.id === id)?.title ?? "内容章节",
    items,
  }));
});
const isMarkdownBusy = computed(
  () => markdownQuery.isPending.value || markdownQuery.isFetching.value,
);
const markdown = computed(() => markdownQuery.data.value?.markdown ?? "");
const actionMessage = ref("");
const message = computed(() => {
  if (actionMessage.value) return actionMessage.value;
  if (taskQuery.isError.value) return "暂时无法读取任务，请重试。";
  if (slidesQuery.isError.value) return "暂时无法读取页面内容，请重试。";
  if (markdownQuery.isError.value) return "暂时无法读取 Markdown，请重试。";
  return "";
});

watch(
  () => task.value,
  (value) => {
    if (!value) return;
    const destination = resolveTaskRoute(value);
    if (route.path !== destination) void router.replace(destination);
  },
  { immediate: true },
);

function selectTab(value: ResultTab): void {
  void router.replace({
    query: { ...route.query, tab: value },
  });
}

function selectPage(pageNumber: number): void {
  void router.replace({
    query: { ...route.query, page: String(pageNumber) },
  });
}

function refreshAfterChatChange(): void {
  for (const key of ["task", "slides", "markdown", "evaluation", "revisions"]) {
    void queryClient.invalidateQueries({ queryKey: [key, taskId] });
  }
}

function revisionTypeLabel(type: string): string {
  return (
    {
      AUTO: "自动修订",
      USER: "用户修改",
      CHAT: "聊天修改",
      UNDO: "撤销修改",
    }[type] ?? "内容修改"
  );
}

function revisionScopeLabel(scope: string[]): string {
  if (!scope.length) return "整份内容";
  const pages = scope
    .map((id) => slides.value.find((slide) => slide.id === id)?.page_number)
    .filter((value): value is number => value !== undefined);
  if (pages.length === scope.length) {
    return `第 ${pages.join("、")} 页`;
  }
  return scope.join("、");
}

async function undoRevision(revisionId: string): Promise<void> {
  if (!task.value) return;
  actionMessage.value = "";
  try {
    await undoChatRevision(taskId, revisionId, task.value.version);
    refreshAfterChatChange();
  } catch (error) {
    actionMessage.value = apiErrorMessage(error, "撤销失败，请刷新后重试。");
  }
}

async function copyMarkdown(): Promise<void> {
  if (!markdown.value) await markdownQuery.refetch();
  const value = markdownQuery.data.value?.markdown;
  if (!value) return;
  try {
    await globalThis.navigator.clipboard.writeText(value);
  } catch {
    actionMessage.value = "无法访问剪贴板。请切换到 Markdown 源码并手动复制。";
  }
}

async function saveMarkdown(): Promise<void> {
  try {
    const file = await downloadMarkdown(taskId);
    const url = globalThis.URL.createObjectURL(file);
    const link = globalThis.document.createElement("a");
    link.href = url;
    link.download = "slideai-content.md";
    link.click();
    globalThis.window.setTimeout(
      () => globalThis.URL.revokeObjectURL(url),
      1000,
    );
  } catch (error) {
    actionMessage.value = apiErrorMessage(error, "Markdown 下载失败，请重试。");
  }
}

function citationLocation(citation: SlideContent["citations"][number]): string {
  const parts = [
    citation.display_name,
    citation.page_number ? `第 ${citation.page_number} 页` : "未标页码",
  ];
  if (citation.section_title) parts.push(citation.section_title);
  return parts.join(" · ");
}
</script>

<template>
  <main class="result-page" aria-labelledby="page-title">
    <header v-if="task" class="task-context">
      <div>
        <h1 id="page-title" :title="task.name">{{ task.name }}</h1>
        <p>
          {{ task.raw_requirement.target_page_count }} 页文字内容
          <span aria-hidden="true">·</span> 版本 {{ task.version }}
        </p>
      </div>
      <div class="page-actions">
        <RouterLink class="button button--secondary" to="/tasks"
          >返回任务中心</RouterLink
        >
        <button
          class="button button--secondary"
          type="button"
          @click="chatOpen = true"
        >
          聊天助手
        </button>
        <button
          class="button button--secondary"
          type="button"
          :disabled="isMarkdownBusy"
          @click="copyMarkdown"
        >
          复制 Markdown
        </button>
        <button
          class="button button--primary"
          type="button"
          @click="saveMarkdown"
        >
          下载 .md
        </button>
      </div>
    </header>

    <div v-else class="task-context" role="status">正在读取任务…</div>

    <div class="workflow-strip" aria-label="工作流进度">
      <span class="workflow-strip__item workflow-strip__item--done"
        >✓ 需求解析</span
      >
      <span class="workflow-strip__item workflow-strip__item--done"
        >✓ 大纲规划</span
      >
      <span class="workflow-strip__item workflow-strip__item--done"
        >✓ 资料检索</span
      >
      <span class="workflow-strip__item workflow-strip__item--done"
        >✓ 内容生成</span
      >
      <span class="workflow-strip__item">5 质量评估</span>
      <span class="workflow-strip__item">6 完成</span>
    </div>

    <div v-if="message" class="page-alert" role="alert">
      {{ message }}
      <button class="text-button" type="button" @click="slidesQuery.refetch()">
        重新加载
      </button>
    </div>

    <nav class="result-tabs" aria-label="结果视图">
      <button
        type="button"
        :aria-current="tab === 'content' ? 'page' : undefined"
        @click="selectTab('content')"
      >
        正文内容
      </button>
      <button
        type="button"
        :aria-current="tab === 'evaluation' ? 'page' : undefined"
        @click="selectTab('evaluation')"
      >
        质量评估
      </button>
      <button
        type="button"
        :aria-current="tab === 'markdown' ? 'page' : undefined"
        @click="selectTab('markdown')"
      >
        Markdown 源码
      </button>
      <button
        type="button"
        :aria-current="tab === 'history' ? 'page' : undefined"
        @click="selectTab('history')"
      >
        修改历史
      </button>
    </nav>

    <div
      v-if="taskQuery.isPending.value || slidesQuery.isPending.value"
      class="result-loading"
      role="status"
    >
      正在读取文字内容…
    </div>
    <section
      v-else-if="tab === 'content'"
      class="content-layout"
      aria-label="正文内容"
    >
      <nav class="content-outline" aria-label="文字目录">
        <h2>内容目录</h2>
        <section
          v-for="section in sections"
          :key="section.id"
          class="outline-section"
        >
          <h3>{{ section.title }}</h3>
          <button
            v-for="slide in section.items"
            :key="slide.id"
            type="button"
            class="outline-page-link"
            :class="{
              'outline-page-link--active': selectedSlide?.id === slide.id,
            }"
            :aria-current="selectedSlide?.id === slide.id ? 'page' : undefined"
            @click="selectPage(slide.page_number)"
          >
            <span>第 {{ slide.page_number }} 页</span>
            <span>{{ slide.title }}</span>
          </button>
        </section>
        <p v-if="!slides.length" class="muted-text">还没有生成页面。</p>
      </nav>

      <article v-if="selectedSlide" class="page-text-section">
        <header class="page-text-section__heading">
          <span>第 {{ selectedSlide.page_number }} 页</span>
          <h2>{{ selectedSlide.title }}</h2>
        </header>
        <ul class="page-bullets">
          <li
            v-for="(bullet, index) in selectedSlide.bullets"
            :key="`${index}-${bullet}`"
          >
            {{ bullet }}
          </li>
        </ul>
        <section v-if="selectedSlide.speaker_notes" class="text-subsection">
          <h3>演讲备注</h3>
          <p>{{ selectedSlide.speaker_notes }}</p>
        </section>
        <section v-if="selectedSlide.citations.length" class="text-subsection">
          <h3>资料依据</h3>
          <ol class="citation-list">
            <li
              v-for="citation in selectedSlide.citations"
              :key="citation.chunk_id"
            >
              <strong>{{ citationLocation(citation) }}</strong>
              <p>{{ citation.excerpt }}</p>
            </li>
          </ol>
        </section>
        <section
          v-if="selectedSlide.verification_notes.length"
          class="text-subsection verification-notes"
        >
          <h3>待核实项</h3>
          <ul>
            <li v-for="note in selectedSlide.verification_notes" :key="note">
              {{ note }}
            </li>
          </ul>
        </section>
      </article>
      <article v-else class="page-text-section page-text-section--empty">
        <h2>尚无页面内容</h2>
        <p>任务生成页面后，正文、备注和资料依据会显示在这里。</p>
      </article>

      <aside class="assistant-placeholder" aria-label="内容助手">
        <h2>内容助手</h2>
        <p v-if="selectedSlide">
          当前对象：第 {{ selectedSlide.page_number }} 页
        </p>
        <p v-else>当前对象：整份内容</p>
        <button
          class="button button--secondary"
          type="button"
          @click="chatOpen = true"
        >
          打开聊天助手
        </button>
      </aside>
    </section>

    <section
      v-else-if="tab === 'markdown'"
      class="markdown-panel"
      aria-label="Markdown 源码"
    >
      <header>
        <div>
          <h2>Markdown 源码</h2>
          <p>保留服务端生成的原始 UTF-8 Markdown。</p>
        </div>
        <div class="page-actions">
          <button
            class="button button--secondary"
            type="button"
            :disabled="isMarkdownBusy || !markdown"
            @click="copyMarkdown"
          >
            复制 Markdown</button
          ><button
            class="button button--primary"
            type="button"
            @click="saveMarkdown"
          >
            下载 .md
          </button>
        </div>
      </header>
      <textarea
        v-if="markdown"
        class="markdown-source"
        aria-label="只读 Markdown 源码"
        readonly
        spellcheck="false"
        :value="markdown"
      />
      <p v-else-if="isMarkdownBusy" role="status">正在读取 Markdown…</p>
      <p v-else>还没有可用的 Markdown 内容。</p>
    </section>

    <EvaluationPanel v-else-if="tab === 'evaluation'" :task-id="taskId" />
    <section v-else class="revision-history" aria-labelledby="history-title">
      <h2 id="history-title">修改历史</h2>
      <p v-if="revisionsQuery.isPending.value" role="status">
        正在读取修改历史…
      </p>
      <p v-else-if="!revisionsQuery.data.value?.items.length">
        还没有修改记录。
      </p>
      <ol v-else class="revision-list">
        <li
          v-for="revision in [...revisionsQuery.data.value.items].reverse()"
          :key="revision.id"
          class="revision-row"
        >
          <div class="revision-row__heading">
            <strong>版本 {{ revision.revision_number }}</strong>
            <span>{{ revisionTypeLabel(revision.revision_type) }}</span>
          </div>
          <p>{{ revision.reason }}</p>
          <div class="revision-row__meta">
            <span>范围：{{ revisionScopeLabel(revision.scope) }}</span>
            <span>
              {{
                revision.score_before === null
                  ? "未评估"
                  : `${revision.score_before} 分`
              }}
              →
              {{
                revision.score_after === null
                  ? "未评估"
                  : `${revision.score_after} 分`
              }}
            </span>
            <time :datetime="revision.created_at">{{
              revision.created_at
            }}</time>
          </div>
          <button
            v-if="revision.can_undo"
            class="button button--secondary"
            type="button"
            @click="undoRevision(revision.id)"
          >
            撤销修改
          </button>
        </li>
      </ol>
    </section>
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
.result-page {
  max-width: 1500px;
  margin: 0 auto;
}
.task-context {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 20px;
}
.task-context h1 {
  max-width: min(60vw, 800px);
  overflow: hidden;
  margin: 0;
  color: var(--color-text-strong);
  font-size: clamp(22px, 3vw, 30px);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.task-context p {
  margin: 6px 0 0;
  color: var(--color-text-muted);
}
.page-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.button {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  justify-content: center;
  padding: 0 14px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  background: white;
  color: var(--color-text-strong);
  font: inherit;
  font-weight: 650;
  text-decoration: none;
  cursor: pointer;
}
.button--primary {
  border-color: var(--color-primary-600);
  background: var(--color-primary-600);
  color: #fff;
}
.button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.workflow-strip {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 18px;
}
.workflow-strip__item {
  display: flex;
  min-height: 50px;
  align-items: center;
  gap: 7px;
  padding: 8px 10px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: white;
  color: var(--color-text-muted);
}
.workflow-strip__item--done {
  border-color: #a9d4f7;
  background: var(--color-primary-050);
  color: var(--color-primary-800);
  font-weight: 650;
}
.result-tabs {
  display: flex;
  gap: 4px;
  overflow: auto;
  border-bottom: 1px solid var(--color-border-strong);
}
.result-tabs button {
  position: relative;
  flex: none;
  padding: 13px 18px;
  border: 0;
  background: transparent;
  color: var(--color-text-muted);
  font: inherit;
  cursor: pointer;
}
.result-tabs button[aria-current="page"] {
  color: var(--color-primary-700);
  font-weight: 700;
}
.result-tabs button[aria-current="page"]::after {
  position: absolute;
  right: 14px;
  bottom: -1px;
  left: 14px;
  height: 3px;
  border-radius: 3px 3px 0 0;
  background: var(--color-primary-600);
  content: "";
}
.content-layout {
  display: grid;
  grid-template-columns: minmax(190px, 0.78fr) minmax(360px, 2fr) minmax(
      220px,
      0.86fr
    );
  align-items: start;
  gap: 20px;
  padding-top: 18px;
}
.content-outline,
.assistant-placeholder {
  padding: 18px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
}
.content-outline h2,
.assistant-placeholder h2 {
  margin: 0 0 14px;
  color: var(--color-text-strong);
  font-size: 16px;
}
.outline-section + .outline-section {
  margin-top: 18px;
}
.outline-section h3 {
  margin: 0 0 6px;
  color: var(--color-text-muted);
  font-size: 13px;
}
.outline-page-link {
  display: grid;
  width: 100%;
  gap: 2px;
  padding: 9px 10px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--color-text);
  text-align: left;
  cursor: pointer;
}
.outline-page-link span:first-child {
  color: var(--color-text-muted);
  font-size: 12px;
}
.outline-page-link span:last-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.outline-page-link--active {
  background: var(--color-primary-050);
  color: var(--color-primary-800);
}
.page-text-section {
  min-width: 0;
  padding: 4px 4px 26px;
  color: var(--color-text);
}
.page-text-section + .page-text-section {
  border-top: 1px solid var(--color-border);
}
.page-text-section__heading {
  padding-bottom: 16px;
  border-bottom: 1px solid var(--color-border);
}
.page-text-section__heading span {
  color: var(--color-primary-700);
  font-size: 13px;
  font-weight: 700;
}
.page-text-section__heading h2 {
  margin: 5px 0 0;
  color: var(--color-text-strong);
  font-size: 25px;
  line-height: 1.35;
}
.page-bullets {
  display: grid;
  gap: 12px;
  padding-left: 24px;
  margin: 20px 0;
  font-size: 15px;
  line-height: 1.7;
}
.text-subsection {
  padding: 17px 0;
  border-top: 1px solid var(--color-border);
}
.text-subsection h3 {
  margin: 0 0 9px;
  color: var(--color-text-strong);
  font-size: 15px;
}
.text-subsection p {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.7;
}
.citation-list {
  display: grid;
  gap: 12px;
  padding-left: 22px;
}
.citation-list li strong {
  color: var(--color-primary-800);
}
.citation-list li p {
  margin-top: 4px;
  color: var(--color-text-muted);
}
.verification-notes {
  color: #855100;
}
.verification-notes ul {
  margin: 0;
  padding-left: 21px;
}
.assistant-placeholder {
  position: sticky;
  top: 84px;
}
.assistant-placeholder p {
  color: var(--color-text-muted);
  line-height: 1.6;
}
.revision-history {
  display: grid;
  gap: 12px;
  margin-top: 18px;
  padding: 22px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
}
.revision-history h2,
.revision-history p {
  margin: 0;
}
.revision-history h2 {
  color: var(--color-text-strong);
}
.revision-list {
  display: grid;
  gap: 0;
  padding: 0;
  margin: 0;
  list-style: none;
}
.revision-row {
  display: grid;
  gap: 8px;
  padding: 15px 0;
  border-top: 1px solid var(--color-border);
}
.revision-row__heading,
.revision-row__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 18px;
}
.revision-row__heading strong {
  color: var(--color-text-strong);
}
.revision-row__meta {
  color: var(--color-text-muted);
  font-size: 12px;
}
.revision-row .button {
  justify-self: start;
}
.markdown-panel,
.not-ready-panel,
.result-loading {
  margin-top: 18px;
  padding: 22px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
}
.markdown-panel > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 16px;
}
.markdown-panel h2,
.not-ready-panel h2 {
  margin: 0;
  color: var(--color-text-strong);
}
.markdown-panel header p,
.not-ready-panel p {
  margin: 5px 0 0;
  color: var(--color-text-muted);
}
.markdown-source {
  display: block;
  width: 100%;
  min-height: 65vh;
  resize: vertical;
  padding: 16px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: #f8fbfe;
  color: var(--color-text-strong);
  font:
    13px/1.65 ui-monospace,
    SFMono-Regular,
    Consolas,
    monospace;
  white-space: pre;
}
.not-ready-panel {
  min-height: 170px;
}
.muted-text {
  color: var(--color-text-muted);
}
.page-alert {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 14px;
  border-radius: 8px;
  background: var(--color-danger-bg);
  color: #a61f35;
}
.text-button {
  border: 0;
  background: transparent;
  color: var(--color-primary-700);
  font: inherit;
  font-weight: 650;
  cursor: pointer;
}
@media (max-width: 1100px) {
  .content-layout {
    grid-template-columns: minmax(180px, 0.7fr) minmax(0, 2fr);
  }
  .assistant-placeholder {
    position: static;
    grid-column: 2;
  }
}
@media (max-width: 760px) {
  .task-context,
  .markdown-panel > header {
    align-items: flex-start;
    flex-direction: column;
  }
  .task-context h1 {
    max-width: 100%;
  }
  .page-actions {
    width: 100%;
  }
  .page-actions .button {
    flex: 1;
  }
  .workflow-strip {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .content-layout {
    grid-template-columns: 1fr;
  }
  .content-outline {
    order: 0;
  }
  .page-text-section {
    order: 1;
  }
  .assistant-placeholder {
    grid-column: auto;
    order: 2;
  }
  .markdown-panel,
  .revision-history {
    padding: 16px;
  }
}
</style>
