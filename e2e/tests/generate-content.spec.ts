import { expect, test } from "@playwright/test";

test("creates a task and completes the Docker fake-provider text workflow", async ({
  page,
}) => {
  const topic = `Compose 演示 ${Date.now()}`;
  await page.goto("/tasks/new");
  await page.getByLabel(/主题/).fill(topic);
  await page.getByLabel(/目标页数/).fill("3");
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
  expect(slides.items.map((slide) => slide.page_number)).toEqual([1, 2, 3]);
  expect(slides.generation_progress).toMatchObject({
    completed_pages: 3,
    total_pages: 3,
  });

  const markdownResponse = await page.request.get(
    `${new URL(page.url()).origin}/api/v1/tasks/${taskId}/markdown`,
  );
  expect(markdownResponse.ok()).toBeTruthy();
  expect((await markdownResponse.json()).markdown).toContain(`# ${topic}`);

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
});
