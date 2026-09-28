import { createRouter, createWebHistory } from "vue-router";
import TaskCenterView from "./views/TaskCenterView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/tasks" },
    { path: "/tasks", name: "task-center", component: TaskCenterView },
  ],
});

export default router;
