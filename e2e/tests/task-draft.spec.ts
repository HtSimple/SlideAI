import { expect, test } from "@playwright/test";
import { Buffer } from "node:buffer";

test("create, edit, and reload a persistent task draft", async ({ page }) => {
  const topic = `Docker 验收任务 ${Date.now()}`;
  let taskId: string | undefined;

  try {
    await page.goto("/tasks/new");
    await page.getByLabel(/主题/).fill(topic);
    await page.getByLabel(/目标页数/).fill("12");
    await page.getByLabel(/使用场景/).fill("面向管理层的季度战略汇报");
    await page.getByLabel(/目标受众/).fill("业务负责人");
    await page.getByLabel(/内容风格/).fill("清晰、务实，以结论为主");
    await page.getByRole("button", { name: "保存草稿" }).click();

    await expect(page.getByRole("heading", { name: "编辑任务" })).toBeVisible();
    taskId = new URL(page.url()).pathname.split("/")[2];
    expect(taskId).toBeTruthy();

    await page.locator("#source-file-input").setInputFiles({
      name: "quarterly-source.md",
      mimeType: "text/markdown",
      buffer: Buffer.from("# Quarterly outlook\n\nRevenue grew 12 percent year over year."),
    });
    await expect(page.getByText("已就绪")).toBeVisible({ timeout: 30000 });
    await expect(page.getByText("quarterly-source.md")).toBeVisible();
    await page.getByRole("button", { name: "移除 quarterly-source.md" }).click();
    await expect(page.getByText("quarterly-source.md")).toHaveCount(0);

    await page.reload();
    await expect(page.getByRole("heading", { name: "编辑任务" })).toBeVisible();
    await page.getByLabel(/目标页数/).fill("15");
    await page.getByRole("button", { name: "保存草稿" }).click();
    await expect(page.getByRole("heading", { name: "任务中心" })).toBeVisible();
    await expect(page.getByRole("link", { name: topic })).toBeVisible();

    const detail = await page.request.get(`http://api:8000/api/v1/tasks/${taskId}`);
    expect(detail.ok()).toBeTruthy();
    const saved = (await detail.json()) as { version: number; raw_requirement: { target_page_count: number } };
    expect(saved.version).toBeGreaterThan(2);
    expect(saved.raw_requirement.target_page_count).toBe(15);
  } finally {
    if (taskId) await page.request.delete(`http://api:8000/api/v1/tasks/${taskId}`);
  }
});
