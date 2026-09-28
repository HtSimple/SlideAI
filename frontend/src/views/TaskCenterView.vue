<script setup lang="ts">
import { RouterLink } from "vue-router";
</script>

<template>
  <section class="task-center" aria-labelledby="page-title">
    <div class="task-center__heading">
      <div>
        <h1 id="page-title">任务中心</h1>
        <p>查看、恢复和管理演示文稿内容生成任务</p>
      </div>
      <RouterLink class="button button--primary" to="/tasks/new">
        创建新任务
      </RouterLink>
    </div>

    <section class="empty-state" aria-labelledby="empty-title">
      <div class="empty-state__mark" aria-hidden="true">文</div>
      <h2 id="empty-title">还没有生成任务</h2>
      <p>创建一个任务，填写演示文稿需求并生成结构化文字内容。</p>
      <RouterLink class="button button--secondary" to="/tasks/new">
        创建新任务
      </RouterLink>
    </section>
  </section>
</template>

<style scoped>
.task-center__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  margin: 0 0 24px;
}

h1 {
  margin: 0;
  color: var(--color-text-strong);
  font-size: 30px;
  line-height: 42px;
}

.task-center__heading p {
  margin: 8px 0 0;
  color: var(--color-text-muted);
  font-size: 14px;
  line-height: 22px;
}

.button {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  justify-content: center;
  padding: 0 16px;
  border: 1px solid var(--color-primary-600);
  border-radius: var(--radius-control);
  font-size: 14px;
  font-weight: 600;
  text-decoration: none;
}

.button:focus-visible {
  outline: 3px solid var(--color-focus);
  outline-offset: 2px;
}

.button--primary {
  background: var(--color-primary-600);
  color: #fff;
}

.button--secondary {
  background: #fff;
  color: var(--color-primary-700);
}

.empty-state {
  display: flex;
  min-height: 320px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
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

.empty-state h2 {
  margin: 20px 0 0;
  color: var(--color-text-strong);
  font-size: 20px;
  line-height: 28px;
}

.empty-state p {
  margin: 8px 0 20px;
  color: var(--color-text-muted);
  font-size: 14px;
  line-height: 22px;
}

@media (max-width: 520px) {
  .task-center__heading {
    align-items: stretch;
    flex-direction: column;
  }

  .task-center__heading .button {
    align-self: flex-start;
  }

  .empty-state {
    min-height: 260px;
    padding: 24px 16px;
  }
}
</style>
