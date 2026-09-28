import { expect, test } from "@playwright/test";

test("complete requirement and outline reviews with page allocation checks", async ({ page }) => {
  const taskId = "workflow-review-e2e";
  const requirement = {
    topic: "产业趋势",
    target_page_count: 6,
    scenario: null as string | null,
    audience: null as string | null,
    style: null as string | null,
    constraints: [],
    language: "zh-CN",
    source_usage: "preferred",
    original_text: "面向管理层，整理产业趋势和行动建议。",
    domain_expertise: "general",
    analysis_depth: "overview",
  };
  const outline = {
    title: "产业趋势",
    sections: [
      {
        id: "overview",
        title: "趋势概览",
        objective: "解释关键趋势",
        page_count: 6,
        items: [
          {
            id: "signals",
            title: "关键变化信号",
            objective: "总结变化信号",
            page_count: 6,
          },
        ],
      },
    ],
  };
  let status = "WAITING_REQUIREMENT_INPUT";
  let currentStage: string | null = "requirement_review";
  let version = 2;

  await page.route(`**/api/v1/tasks/${taskId}**`, async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    const task = {
      id: taskId,
      name: requirement.topic,
      status,
      current_stage: currentStage,
      raw_requirement: {
        topic: requirement.topic,
        target_page_count: requirement.target_page_count,
        scenario: "面向管理层的经营分析",
        audience: "管理层",
        style: "结论先行",
        special_constraints: [],
      },
      model_preference: { mode: "auto", model_key: null },
      complexity: {
        tier: "fast",
        total_score: 3,
        factors: { page_count: 1, sources: 0, constraints: 0, expertise: 1, depth: 1 },
      },
      structured_requirement: requirement,
      outline,
      version,
      created_at: "2026-09-28T00:00:00Z",
      updated_at: "2026-09-28T00:00:00Z",
    };

    if (url.pathname === `/api/v1/tasks/${taskId}` && method === "GET") {
      await route.fulfill({ json: task });
      return;
    }

    if (url.pathname === `/api/v1/tasks/${taskId}/requirement` && method === "GET") {
      await route.fulfill({
        json: {
          task_id: taskId,
          status,
          version,
          structured_requirement: requirement,
          missing_fields: ["scenario", "audience", "style"],
        },
      });
      return;
    }

    if (url.pathname === `/api/v1/tasks/${taskId}/requirement` && method === "PUT") {
      const body = route.request().postDataJSON() as {
        expected_version: number;
        structured_requirement: typeof requirement;
      };
      expect(body.expected_version).toBe(version);
      Object.assign(requirement, body.structured_requirement);
      version += 1;
      await route.fulfill({
        json: {
          task_id: taskId,
          status,
          version,
          structured_requirement: requirement,
          missing_fields: [],
        },
      });
      return;
    }

    if (
      url.pathname === `/api/v1/tasks/${taskId}/requirement/confirm` &&
      method === "POST"
    ) {
      const body = route.request().postDataJSON() as { expected_version: number };
      expect(body.expected_version).toBe(version);
      version += 1;
      status = "WAITING_OUTLINE_CONFIRMATION";
      currentStage = "outline_review";
      await route.fulfill({
        status: 202,
        json: { task_id: taskId, status: "RUNNING", current_stage: "outline", version },
      });
      return;
    }

    if (url.pathname === `/api/v1/tasks/${taskId}/outline` && method === "GET") {
      await route.fulfill({
        json: { task_id: taskId, status, version, outline, issues: [] },
      });
      return;
    }

    if (url.pathname === `/api/v1/tasks/${taskId}/outline` && method === "PUT") {
      const body = route.request().postDataJSON() as {
        expected_version: number;
        outline: typeof outline;
      };
      expect(body.expected_version).toBe(version);
      Object.assign(outline, body.outline);
      version += 1;
      await route.fulfill({
        json: { task_id: taskId, status, version, outline, issues: [] },
      });
      return;
    }

    if (url.pathname === `/api/v1/tasks/${taskId}/outline/confirm` && method === "POST") {
      const body = route.request().postDataJSON() as { expected_version: number };
      expect(body.expected_version).toBe(version);
      version += 1;
      status = "READY";
      currentStage = "outline_confirmed";
      await route.fulfill({
        status: 202,
        json: { task_id: taskId, status, current_stage: currentStage, version },
      });
      return;
    }

    await route.continue();
  });

  await page.goto(`/tasks/${taskId}/requirement`);
  await expect(page.getByRole("heading", { name: "确认内容需求" })).toBeVisible();
  await page.getByLabel(/使用场景/).fill("年度经营分析");
  await page.getByLabel(/目标受众/).fill("业务管理层");
  await page.getByLabel(/内容风格/).fill("数据驱动、结论先行");
  await page.getByRole("button", { name: "确认需求并生成大纲" }).click();

  await expect(page.getByRole("heading", { name: "检查并编辑大纲" })).toBeVisible();
  await page.getByLabel("章节页数").fill("5");
  await page.getByLabel("页数", { exact: true }).fill("5");
  await expect(page.getByText("需调整")).toBeVisible();
  await expect(page.getByRole("button", { name: "确认大纲并开始生成" })).toBeDisabled();

  await page.getByLabel("章节页数").fill("6");
  await page.getByLabel("页数", { exact: true }).fill("6");
  await page.getByLabel("条目标题").fill("趋势驱动因素");
  await page.getByRole("button", { name: "确认大纲并开始生成" }).click();
  await expect(page.getByRole("heading", { name: "大纲已确认" })).toBeVisible();
  expect(outline.sections[0]?.items[0]?.title).toBe("趋势驱动因素");
});
