<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useChatAssistant } from "../../composables/useChatAssistant";
import type { ChatTarget } from "../../types/chat";

const props = defineProps<{
  taskId: string;
  taskVersion: number;
  open: boolean;
  target?: ChatTarget | null;
}>();
const emit = defineEmits<{
  close: [];
  updated: [];
}>();
const composer = ref<{ focus: () => void } | null>(null);
const target = computed(() => props.target ?? null);
const targetLabel = computed(
  () => target.value?.label ?? (target.value ? "当前选择对象" : "整份内容"),
);
const assistant = useChatAssistant({
  taskId: props.taskId,
  taskVersion: () => props.taskVersion,
  open: () => props.open,
  target,
  onUpdated: () => emit("updated"),
});
watch(
  () => props.open,
  async (open) => {
    if (!open) return;
    await nextTick();
    composer.value?.focus();
  },
);

function isLatestUndoable(revisionId?: string | null): boolean {
  return assistant.messages.value.some(
    (message) => message.revision_id === revisionId && message.can_undo,
  );
}
</script>

<template>
  <div v-if="open" class="chat-layer" @click.self="emit('close')">
    <aside class="chat-drawer" role="complementary" aria-label="聊天助手">
      <header class="chat-drawer__header">
        <h2>聊天助手</h2>
        <button
          class="chat-close"
          type="button"
          aria-label="关闭聊天助手"
          @click="emit('close')"
        >
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <path d="m5 5 10 10M15 5 5 15" />
          </svg>
        </button>
      </header>

      <p class="chat-context">当前对象：{{ targetLabel }}</p>

      <div class="chat-messages" role="log" aria-live="polite">
        <p v-if="assistant.historyQuery.isPending.value" class="chat-empty">
          正在读取对话…
        </p>
        <p v-else-if="!assistant.messages.value.length" class="chat-empty">
          描述希望调整的大纲条目、章节或页面。
        </p>
        <article
          v-for="message in assistant.messages.value"
          :key="message.id"
          class="chat-message"
          :class="`chat-message--${message.role}`"
        >
          <p class="chat-message__content">{{ message.content }}</p>

          <section
            v-if="
              message.role === 'assistant' &&
              message.change_request?.status === 'NEEDS_CLARIFICATION'
            "
            class="chat-card chat-card--clarification"
            aria-label="澄清问题"
          >
            <strong>需要补充信息</strong>
            <p>
              {{
                message.change_request.clarification_question ?? message.content
              }}
            </p>
          </section>

          <section
            v-if="
              message.role === 'assistant' &&
              message.change_request?.status === 'NEEDS_CONFIRMATION'
            "
            class="chat-card chat-card--confirmation"
            aria-label="影响确认"
          >
            <strong>影响范围</strong>
            <p v-if="message.change_request.affected_pages.length">
              将修改第
              {{ message.change_request.affected_pages.join("、") }} 页
            </p>
            <p v-else>将影响所选的大纲对象。</p>
            <p v-if="message.change_request.replacement_text">
              修改为：{{ message.change_request.replacement_text }}
            </p>
            <button
              class="chat-action chat-action--primary"
              type="button"
              :disabled="assistant.busy.value"
              @click="assistant.confirm(message.change_request.id)"
            >
              确认并执行
            </button>
          </section>

          <section
            v-if="message.role === 'assistant' && message.revision_id"
            class="chat-card chat-card--result"
            aria-label="执行结果"
          >
            <strong>修改结果</strong>
            <p>{{ message.content }}</p>
            <div class="chat-card__actions">
              <button
                v-if="isLatestUndoable(message.revision_id)"
                class="chat-action"
                type="button"
                :disabled="assistant.busy.value"
                @click="assistant.undo(message.revision_id!)"
              >
                撤销修改
              </button>
              <button
                class="chat-action"
                type="button"
                :disabled="assistant.busy.value"
                @click="composer?.focus()"
              >
                再次修改
              </button>
            </div>
          </section>
        </article>
      </div>

      <p v-if="assistant.error.value" class="chat-error" role="alert">
        {{ assistant.error.value }}
      </p>
      <form class="chat-composer" @submit.prevent="assistant.send">
        <label class="sr-only" for="chat-message-input">输入修改要求</label>
        <textarea
          id="chat-message-input"
          ref="composer"
          v-model="assistant.draft.value"
          rows="3"
          maxlength="4000"
          placeholder="描述你希望如何修改…"
          :disabled="assistant.busy.value"
        />
        <div class="chat-composer__footer">
          <span>Enter 换行</span>
          <button
            class="chat-action chat-action--primary"
            type="submit"
            :disabled="assistant.busy.value || !assistant.draft.value.trim()"
          >
            {{ assistant.busy.value ? "处理中…" : "发送" }}
          </button>
        </div>
      </form>
    </aside>
  </div>
</template>

<style scoped>
.chat-layer {
  position: fixed;
  z-index: 50;
  inset: 0;
  display: flex;
  justify-content: flex-end;
  pointer-events: none;
}
.chat-drawer {
  display: flex;
  width: 380px;
  max-width: 100vw;
  height: 100%;
  flex-direction: column;
  border-left: 1px solid var(--color-border);
  background: var(--color-surface);
  box-shadow: var(--shadow-panel);
  pointer-events: auto;
}
.chat-drawer__header {
  display: flex;
  min-height: 64px;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  border-bottom: 1px solid var(--color-border);
}
.chat-drawer__header h2 {
  margin: 0;
  color: var(--color-text-strong);
  font-size: 17px;
  line-height: 24px;
}
.chat-close {
  display: grid;
  width: 36px;
  height: 36px;
  place-items: center;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: white;
  color: var(--color-text-muted);
  cursor: pointer;
}
.chat-close svg {
  width: 18px;
  height: 18px;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-width: 1.7;
}
.chat-context {
  flex: none;
  margin: 0;
  padding: 12px 20px;
  background: var(--color-primary-050);
  color: var(--color-primary-800);
  font-size: 13px;
  font-weight: 650;
}
.chat-messages {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  gap: 14px;
  overflow-y: auto;
  padding: 18px 16px;
}
.chat-empty {
  margin: 0;
  padding: 14px 4px;
  color: var(--color-text-muted);
  text-align: center;
}
.chat-message {
  display: grid;
  max-width: 94%;
  gap: 8px;
  align-self: flex-start;
}
.chat-message--user {
  align-self: flex-end;
}
.chat-message__content {
  margin: 0;
  padding: 10px 12px;
  border: 1px solid var(--color-border);
  border-radius: 10px 10px 10px 3px;
  background: var(--color-surface-muted);
  color: var(--color-text);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.chat-message--user .chat-message__content {
  border-color: #c9e5fc;
  border-radius: 10px 10px 3px 10px;
  background: var(--color-primary-050);
}
.chat-card {
  display: grid;
  gap: 7px;
  padding: 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: white;
  color: var(--color-text);
}
.chat-card strong {
  color: var(--color-text-strong);
  font-size: 13px;
}
.chat-card p {
  margin: 0;
  line-height: 1.55;
}
.chat-card--clarification {
  border-color: #c6e0f5;
  background: var(--color-info-bg);
}
.chat-card--confirmation {
  border-color: #f0ddb2;
  background: #fffdf7;
}
.chat-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.chat-action {
  display: inline-flex;
  min-height: 34px;
  align-items: center;
  justify-content: center;
  padding: 0 11px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  background: white;
  color: var(--color-primary-700);
  font-size: 13px;
  font-weight: 650;
  cursor: pointer;
}
.chat-action--primary {
  border-color: var(--color-primary-600);
  background: var(--color-primary-600);
  color: white;
}
.chat-action:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.chat-error {
  flex: none;
  margin: 0;
  padding: 8px 16px;
  background: var(--color-danger-bg);
  color: #a61f35;
}
.chat-composer {
  display: grid;
  flex: none;
  gap: 9px;
  padding: 13px 16px max(16px, env(safe-area-inset-bottom));
  border-top: 1px solid var(--color-border);
  background: white;
}
.chat-composer textarea {
  width: 100%;
  min-height: 76px;
  resize: vertical;
  padding: 10px 11px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  color: var(--color-text);
  font-size: 14px;
  line-height: 21px;
}
.chat-composer textarea::placeholder {
  color: var(--color-text-muted);
}
.chat-composer__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--color-text-muted);
  font-size: 12px;
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
@media (max-width: 1279px) {
  .chat-layer {
    background: rgb(16 42 86 / 28%);
    pointer-events: auto;
  }
  .chat-drawer {
    width: min(380px, 100vw);
  }
}
@media (max-width: 480px) {
  .chat-drawer {
    width: 100%;
    border-left: 0;
  }
}
</style>
