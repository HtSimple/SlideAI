<script setup lang="ts">
import { computed } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { getEvaluation, getRevisions } from "../../api/evaluation";

const props = defineProps<{ taskId: string }>();
const evaluationQuery = useQuery({
  queryKey: ["evaluation", props.taskId],
  queryFn: () => getEvaluation(props.taskId),
});
const revisionsQuery = useQuery({
  queryKey: ["revisions", props.taskId],
  queryFn: () => getRevisions(props.taskId),
});
const result = computed(() => evaluationQuery.data.value?.evaluation_result);
const dimensions = computed(() =>
  (result.value?.dimensions ?? []).map((dimension) => ({
    ...dimension,
    label:
      {
        completeness: "完整性",
        logic: "逻辑性",
        content_quality: "内容质量",
        requirement_alignment: "需求符合度",
      }[dimension.name] ?? dimension.name,
  })),
);

function revisionType(value: string): string {
  return value === "AUTO" ? "自动修订" : value === "USER" ? "用户意见" : value;
}
</script>

<template>
  <section class="evaluation-panel" aria-labelledby="evaluation-title">
    <div v-if="evaluationQuery.isPending.value" role="status">
      正在读取质量评估…
    </div>
    <div v-else-if="evaluationQuery.isError.value" role="alert">
      暂时无法读取质量评估，请稍后重试。
      <button
        class="text-button"
        type="button"
        @click="evaluationQuery.refetch()"
      >
        重新加载
      </button>
    </div>
    <template v-else-if="result">
      <header class="evaluation-header">
        <div>
          <h2 id="evaluation-title">质量评估</h2>
          <p>
            四项质量维度等权计算，分数达到
            {{ result.threshold }} 且硬规则全部通过即可通过。
          </p>
        </div>
        <div
          class="evaluation-score"
          :class="
            result.passed
              ? 'evaluation-score--pass'
              : 'evaluation-score--review'
          "
          :aria-label="`总分 ${result.total_score}，${result.passed ? '通过' : '需关注'}`"
        >
          <strong>{{ result.total_score }}</strong>
          <span>{{ result.passed ? "已通过" : "需关注" }}</span>
        </div>
      </header>

      <section class="evaluation-section" aria-labelledby="dimension-title">
        <h3 id="dimension-title">质量维度</h3>
        <ul class="dimension-list">
          <li v-for="item in dimensions" :key="item.name">
            <div class="dimension-heading">
              <strong>{{ item.label }}</strong>
              <span>{{ item.score }} / 100 · {{ item.weight }}%</span>
            </div>
            <div
              class="dimension-track"
              role="progressbar"
              :aria-label="item.label"
              aria-valuemin="0"
              aria-valuemax="100"
              :aria-valuenow="item.score"
            >
              <span :style="{ width: `${item.score}%` }" />
            </div>
            <p>{{ item.feedback }}</p>
          </li>
        </ul>
      </section>

      <section class="evaluation-section" aria-labelledby="checks-title">
        <h3 id="checks-title">硬规则检查</h3>
        <ul class="check-list">
          <li v-for="check in result.hard_checks" :key="check.code">
            <span
              :class="
                check.passed ? 'check-mark--passed' : 'check-mark--failed'
              "
            >
              {{ check.passed ? "通过" : check.blocking ? "阻塞" : "未通过" }}
            </span>
            <span>{{ check.description }}</span>
          </li>
        </ul>
      </section>

      <section class="evaluation-section" aria-labelledby="issues-title">
        <h3 id="issues-title">问题与建议</h3>
        <ul v-if="result.issues.length" class="issue-list">
          <li
            v-for="issue in result.issues"
            :key="issue.code + issue.description"
          >
            <strong>{{ issue.description }}</strong>
            <p>{{ issue.suggestion }}</p>
            <small v-if="issue.scope.length"
              >影响 {{ issue.scope.length }} 页</small
            >
          </li>
        </ul>
        <p v-else class="muted-text">没有待处理的问题。</p>
        <ul v-if="result.suggestions.length" class="suggestion-list">
          <li v-for="suggestion in result.suggestions" :key="suggestion">
            {{ suggestion }}
          </li>
        </ul>
      </section>

      <section class="evaluation-section" aria-labelledby="history-title">
        <h3 id="history-title">修订记录</h3>
        <div v-if="revisionsQuery.isPending.value" role="status">
          正在读取修订记录…
        </div>
        <p
          v-else-if="!revisionsQuery.data.value?.items.length"
          class="muted-text"
        >
          尚无修订记录。
        </p>
        <ol v-else class="revision-list">
          <li
            v-for="revision in revisionsQuery.data.value.items"
            :key="revision.id"
          >
            <div class="revision-list__heading">
              <strong
                >第 {{ revision.revision_number }} 次{{
                  revisionType(revision.revision_type)
                }}</strong
              >
              <span>{{ revision.score_before ?? "—" }} 分</span>
            </div>
            <p>{{ revision.reason }}</p>
            <small>涉及 {{ revision.scope.length }} 页</small>
          </li>
        </ol>
      </section>
    </template>
  </section>
</template>

<style scoped>
.evaluation-panel {
  display: grid;
  gap: 22px;
  padding: 22px;
  margin-top: 18px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
}
.evaluation-header,
.dimension-heading,
.revision-list__heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.evaluation-header h2,
.evaluation-section h3 {
  margin: 0;
  color: var(--color-text-strong);
}
.evaluation-header p,
.dimension-list p,
.issue-list p,
.revision-list p {
  margin: 7px 0 0;
  color: var(--color-text-muted);
  line-height: 1.6;
}
.evaluation-score {
  display: grid;
  min-width: 92px;
  min-height: 82px;
  justify-items: center;
  align-content: center;
  border-radius: 12px;
}
.evaluation-score strong {
  font-size: 30px;
  line-height: 1.1;
}
.evaluation-score--pass {
  background: var(--color-primary-050);
  color: var(--color-primary-800);
}
.evaluation-score--review {
  background: var(--color-warning-bg);
  color: #855100;
}
.evaluation-section {
  display: grid;
  gap: 12px;
  padding-top: 18px;
  border-top: 1px solid var(--color-border);
}
.dimension-list,
.check-list,
.issue-list,
.suggestion-list,
.revision-list {
  display: grid;
  gap: 14px;
  padding: 0;
  margin: 0;
  list-style: none;
}
.dimension-list li,
.issue-list li,
.revision-list li {
  padding: 13px;
  border: 1px solid var(--color-border);
  border-radius: 9px;
}
.dimension-heading span,
.revision-list__heading span,
.issue-list small,
.revision-list small {
  color: var(--color-text-muted);
  font-size: 13px;
}
.dimension-track {
  height: 8px;
  overflow: hidden;
  margin-top: 9px;
  border-radius: 999px;
  background: #e9eef3;
}
.dimension-track span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--color-primary-600);
}
.check-list li {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.check-mark--passed,
.check-mark--failed {
  flex: none;
  min-width: 48px;
  font-weight: 700;
}
.check-mark--passed {
  color: var(--color-primary-700);
}
.check-mark--failed {
  color: #a61f35;
}
.issue-list strong {
  color: var(--color-text-strong);
}
.suggestion-list {
  padding-left: 22px;
  list-style: disc;
  color: var(--color-text-muted);
}
.muted-text {
  margin: 0;
  color: var(--color-text-muted);
}
.text-button {
  border: 0;
  background: transparent;
  color: var(--color-primary-700);
  font: inherit;
  font-weight: 650;
  cursor: pointer;
}
@media (max-width: 600px) {
  .evaluation-panel {
    padding: 15px;
  }
  .evaluation-header {
    align-items: flex-start;
  }
}
</style>
