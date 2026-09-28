import { createRouter, createWebHistory } from "vue-router";
import TaskCenterView from "./views/TaskCenterView.vue";
import TaskEditView from "./views/TaskEditView.vue";
import RequirementReviewView from "./views/RequirementReviewView.vue";
import OutlineEditorView from "./views/OutlineEditorView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/tasks" },
    { path: "/tasks", name: "task-center", component: TaskCenterView },
    { path: "/tasks/new", name: "task-new", component: TaskEditView },
    { path: "/tasks/:taskId/edit", name: "task-edit", component: TaskEditView },
    {
      path: "/tasks/:taskId/requirement",
      name: "task-requirement",
      component: RequirementReviewView,
    },
    {
      path: "/tasks/:taskId/outline",
      name: "task-outline",
      component: OutlineEditorView,
    },
  ],
});

export default router;
