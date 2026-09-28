<script setup lang="ts">
import { onMounted, ref } from "vue";
import { getHealth } from "../api/health";

type HealthState = "checking" | "ready" | "unavailable";

const state = ref<HealthState>("checking");

async function refreshHealth(): Promise<void> {
  state.value = "checking";
  try {
    const result = await getHealth();
    state.value = result.status === "ready" ? "ready" : "unavailable";
  } catch {
    state.value = "unavailable";
  }
}

onMounted(refreshHealth);
</script>

<template>
  <button
    class="health-status"
    type="button"
    :disabled="state === 'checking'"
    @click="refreshHealth"
  >
    <span
      class="health-status__dot"
      :class="`health-status__dot--${state}`"
      aria-hidden="true"
    />
    <span role="status" aria-live="polite">
      {{
        state === "ready"
          ? "服务已就绪"
          : state === "checking"
            ? "正在检查服务状态"
            : "服务暂不可用"
      }}
    </span>
  </button>
</template>

<style scoped>
.health-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 0;
  border-radius: var(--radius-control);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  font: inherit;
}

.health-status:disabled {
  cursor: wait;
}

.health-status__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-warning);
}

.health-status__dot--ready {
  background: var(--color-success);
}

.health-status__dot--unavailable {
  background: var(--color-danger);
}
</style>
