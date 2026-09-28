<script setup lang="ts">
import { RouterLink, RouterView } from "vue-router";
import HealthStatus from "../components/HealthStatus.vue";
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <RouterLink class="brand" to="/tasks" aria-label="SlideAI 任务中心">
        <span class="brand__slide">Slide</span><span class="brand__ai">AI</span>
      </RouterLink>
      <nav class="app-nav" aria-label="主导航">
        <RouterLink
          class="app-nav__link"
          active-class="app-nav__link--active"
          to="/tasks"
        >
          任务中心
        </RouterLink>
        <RouterLink
          class="app-nav__link"
          active-class="app-nav__link--active"
          to="/tasks/new"
        >
          新建任务
        </RouterLink>
      </nav>
      <div class="app-header__status">
        <HealthStatus />
      </div>
    </header>
    <main class="app-main">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.app-shell {
  min-height: 100vh;
  background: var(--color-page-bg);
}

.app-header {
  position: sticky;
  z-index: 10;
  top: 0;
  display: flex;
  align-items: center;
  min-height: 64px;
  padding: 0 32px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-header-bg);
}

.brand {
  display: inline-flex;
  align-items: center;
  min-width: 150px;
  color: var(--color-text-strong);
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.7px;
  text-decoration: none;
}

.brand__ai {
  color: var(--color-primary-600);
}

.app-nav {
  display: flex;
  align-self: stretch;
  gap: 24px;
}

.app-nav__link {
  position: relative;
  display: inline-flex;
  align-items: center;
  padding: 0 8px;
  color: var(--color-text);
  font-size: 14px;
  text-decoration: none;
}

.app-nav__link--active {
  color: var(--color-primary-700);
  font-weight: 600;
}

.app-nav__link--active::after {
  position: absolute;
  right: 8px;
  bottom: 0;
  left: 8px;
  height: 3px;
  border-radius: 3px 3px 0 0;
  background: var(--color-primary-600);
  content: "";
}

.app-header__status {
  display: flex;
  justify-content: flex-end;
  margin-left: auto;
}

.app-main {
  width: min(100%, 1600px);
  margin: 0 auto;
  padding: 32px;
}

@media (max-width: 767px) {
  .app-header {
    min-height: 58px;
    padding: 0 16px;
  }

  .brand {
    min-width: auto;
    margin-right: 16px;
    font-size: 20px;
  }

  .app-nav {
    gap: 8px;
  }

  .app-nav__link {
    padding: 0 6px;
    font-size: 13px;
  }

  .app-header__status {
    display: none;
  }

  .app-main {
    padding: 24px 16px;
  }
}
</style>
