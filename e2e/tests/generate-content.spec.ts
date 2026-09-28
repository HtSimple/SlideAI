import { expect, test } from "@playwright/test";

test("creates a task and completes the Docker fake-provider text workflow", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const topic = `Compose 演示 ${Date.now()}`;
  await page.goto("/tasks/new");
  await page.getByLabel(/主题/).fill(topic);
  await page.getByLabel(/目标页数/).fill("4");
  await page.getByLabel(/使用场景/).fill("季度经营汇报");
  await page.getByLabel(/目标受众/).fill("管理团队");
  await page.getByLabel(/内容风格/).fill("简明、结论先行");

  await page.getByRole("button", { name: "保存草稿" }).click();
  await expect(page).toHaveURL(/\/tasks\/.+\/edit$/);
  await page.getByRole("button", { name: "解析需求" }).click();

  await expect(page.getByRole("heading", { name: "检查并编辑大纲" })).toBeVisible({
    timeout: 30_000,
  });
  await page.getByRole("button", { name: "确认大纲并开始生成" }).click();

  await expect(page).toHaveURL(/\/tasks\/.+\/progress$/);
  await expect(
    page.getByRole("button", { name: "接受当前结果" }),
  ).toBeVisible({ timeout: 90_000 });
  await expect(page.getByRole("heading", { name: "质量评估：80 分" })).toBeVisible();
  const waitingTaskId = new URL(page.url()).pathname.split("/")[2];
  const evaluationResponse = await page.request.get(
    `${new URL(page.url()).origin}/api/v1/tasks/${waitingTaskId}/evaluation`,
  );
  expect(evaluationResponse.ok()).toBeTruthy();
  expect(await evaluationResponse.json()).toMatchObject({
    revision_count: 2,
    evaluation_result: { total_score: 80, passed: false },
  });
  const revisionResponse = await page.request.get(
    `${new URL(page.url()).origin}/api/v1/tasks/${waitingTaskId}/revisions`,
  );
  expect(revisionResponse.ok()).toBeTruthy();
  expect((await revisionResponse.json()).items).toHaveLength(2);

  const userFeedback = "请把第 1 页要点改为面向管理团队的行动建议";
  await page.getByRole("checkbox", { name: /第 1 页/ }).check();
  await page.getByLabel("修改意见").fill(userFeedback);
  await page.getByRole("button", { name: "提交意见并继续" }).click();
  await expect
    .poll(
      async () => {
        const response = await page.request.get(
          `${new URL(page.url()).origin}/api/v1/tasks/${waitingTaskId}/revisions`,
        );
        if (!response.ok()) return 0;
        return ((await response.json()) as { items: unknown[] }).items.length;
      },
      { timeout: 90_000 },
    )
    .toBe(3);
  await expect(
    page.getByRole("button", { name: "接受当前结果" }),
  ).toBeVisible({ timeout: 90_000 });
  const revisedEvaluation = await page.request.get(
    `${new URL(page.url()).origin}/api/v1/tasks/${waitingTaskId}/evaluation`,
  );
  expect((await revisedEvaluation.json()).revision_count).toBe(2);
  const revisedHistory = await page.request.get(
    `${new URL(page.url()).origin}/api/v1/tasks/${waitingTaskId}/revisions`,
  );
  const revisions = (await revisedHistory.json()).items;
  expect(revisions).toHaveLength(3);
  expect(revisions[2]).toMatchObject({ revision_type: "USER", scope: [expect.any(String)] });
  expect(revisions[2].after_slides[0].bullets.join(" ")).toContain(userFeedback);

  await page.getByRole("button", { name: "接受当前结果" }).click();
  await expect(page).toHaveURL(/\/tasks\/.+\/result$/, { timeout: 90_000 });
  await expect(
    page.getByRole("heading", { name: topic, exact: true, level: 1 }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "内容目录" })).toBeVisible();
  const taskId = new URL(page.url()).pathname.split("/")[2];
  const slidesResponse = await page.request.get(
    `${new URL(page.url()).origin}/api/v1/tasks/${taskId}/slides`,
  );
  expect(slidesResponse.ok()).toBeTruthy();
  const slides = (await slidesResponse.json()) as {
    items: { page_number: number }[];
    generation_progress: { completed_pages: number; total_pages: number };
  };
  expect(slides.items.map((slide) => slide.page_number)).toEqual([1, 2, 3, 4]);
  expect(slides.generation_progress).toMatchObject({
    completed_pages: 4,
    total_pages: 4,
  });

  const markdownResponse = await page.request.get(
    `${new URL(page.url()).origin}/api/v1/tasks/${taskId}/markdown`,
  );
  expect(markdownResponse.ok()).toBeTruthy();
  expect((await markdownResponse.json()).markdown).toContain(`# ${topic}`);

  await page.getByRole("button", { name: "质量评估" }).click();
  await expect(page.getByRole("heading", { name: "质量评估" })).toBeVisible();
  await expect(page.getByText("80 / 100 · 25%", { exact: true })).toHaveCount(4);

  await page.getByRole("button", { name: "Markdown 源码" }).click();
  await expect(page).toHaveURL(/tab=markdown/);
  expect(await page.getByLabel("只读 Markdown 源码").inputValue()).toContain(topic);

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "下载 .md" }).first().click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.md$/);

  await page.reload();
  await expect(page.getByRole("button", { name: "Markdown 源码" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(await page.getByLabel("只读 Markdown 源码").inputValue()).toContain(topic);

  const contentBeforeChat = (await slidesResponse.json()) as {
    items: { id: string; page_number: number; title: string; bullets: string[] }[];
  };
  await page.getByRole("button", { name: "聊天助手", exact: true }).click();
  await page.getByLabel("输入修改要求").fill("请把第一页的标题改成市场行动建议");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.locator('[aria-label="执行结果"]')).toContainText("修改已完成");
  await expect(page.locator('[aria-label="影响确认"]')).toHaveCount(0);
  await expect(page.getByRole("button", { name: "撤销修改" })).toBeVisible();

  const changedSlidesResponse = await page.request.get(
    `${new URL(page.url()).origin}/api/v1/tasks/${taskId}/slides`,
  );
  const changedSlides = (await changedSlidesResponse.json()) as typeof contentBeforeChat;
  expect(changedSlides.items[0]?.bullets).not.toEqual(contentBeforeChat.items[0]?.bullets);
  expect(changedSlides.items[0]?.bullets.join(" ")).toContain(
    "请把第一页的标题改成市场行动建议",
  );
  expect(changedSlides.items.slice(1)).toEqual(contentBeforeChat.items.slice(1));

  await page.reload();
  await page.getByRole("button", { name: "聊天助手", exact: true }).click();
  await expect(page.getByText("请把第一页的标题改成市场行动建议")).toBeVisible();
  await expect(page.locator('[aria-label="执行结果"]')).toContainText("修改已完成");
  await page.getByRole("button", { name: "撤销修改" }).click();

  await expect
    .poll(async () => {
      const response = await page.request.get(
        `${new URL(page.url()).origin}/api/v1/tasks/${taskId}/slides`,
      );
      if (!response.ok()) return [];
      return ((await response.json()) as typeof contentBeforeChat).items;
    })
    .toEqual(contentBeforeChat.items);
});
