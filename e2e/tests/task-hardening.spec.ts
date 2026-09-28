import { expect, test, type APIRequestContext } from "@playwright/test";
import { Buffer } from "node:buffer";

const api = "http://api:8000/api/v1";

async function createDraft(request: APIRequestContext, topic: string) {
  const response = await request.post(`${api}/tasks`, {
    data: {
      raw_requirement: {
        topic,
        target_page_count: 3,
        scenario: "项目验收",
        audience: "项目团队",
        style: "简明",
        special_constraints: [],
      },
      model_preference: { mode: "auto" },
    },
  });
  expect(response.status()).toBe(201);
  return (await response.json()) as {
    id: string;
    name: string;
    version: number;
    status: string;
  };
}

test("task center search returns only matching task names", async ({ page }) => {
  const match = `搜索验收-${Date.now()}`;
  const other = `无关任务-${Date.now()}`;
  const first = await createDraft(page.request, match);
  const second = await createDraft(page.request, other);
  try {
    await page.goto("/tasks");
    await page.getByLabel("搜索任务").fill(match);
    await page.getByRole("button", { name: "搜索" }).click();
    await expect(page.getByRole("link", { name: match, exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: other, exact: true })).toHaveCount(0);
    for (const width of [375, 768, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await expect(page.getByRole("heading", { name: "任务中心" })).toBeVisible();
      const layout = await page.evaluate(() => ({
        viewportWidth: window.innerWidth,
        documentWidth: document.documentElement.scrollWidth,
        containers: [".app-main", ".task-center", ".task-panel", ".table-scroll"].map(
          (selector) => {
            const element = document.querySelector(selector);
            if (!element) return { selector, missing: true };
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            return {
              selector,
              left: Math.round(rect.left),
              right: Math.round(rect.right),
              width: Math.round(rect.width),
              clientWidth: element.clientWidth,
              scrollWidth: element.scrollWidth,
              overflowX: style.overflowX,
            };
          },
        ),
        elements: Array.from(document.querySelectorAll("body *"))
          .map((element) => {
            const rect = element.getBoundingClientRect();
            return {
              name: `${element.tagName.toLowerCase()}${element.id ? `#${element.id}` : ""}${
                typeof element.className === "string" && element.className
                  ? `.${element.className.replaceAll(" ", ".")}`
                  : ""
              }`,
              left: Math.round(rect.left),
              right: Math.round(rect.right),
            };
          })
          .filter((element) => element.right > window.innerWidth + 1)
          .slice(0, 10),
      }));
      expect(
        layout.documentWidth,
        JSON.stringify({ containers: layout.containers, elements: layout.elements }),
      ).toBeLessThanOrEqual(width);
    }
  } finally {
    await page.request.delete(`${api}/tasks/${first.id}`);
    await page.request.delete(`${api}/tasks/${second.id}`);
  }
});


test("new task form rejects a page count outside the supported range", async ({ page }) => {
  await page.goto("/tasks/new");
  await page.getByLabel(/主题/).fill(`页数校验-${Date.now()}`);
  await page.getByLabel(/目标页数/).fill("2");
  await page.getByLabel(/使用场景/).fill("项目验收");
  await page.getByLabel(/目标受众/).fill("项目团队");
  await page.getByLabel(/内容风格/).fill("简明");
  await page.getByRole("button", { name: "保存草稿" }).click();
  await expect(page.getByText("目标页数需在 3–50 页之间。")).toBeVisible();
  await expect(page).toHaveURL(/\/tasks\/new$/);
});

test("unsupported reference files show an actionable upload error", async ({ page }) => {
  const task = await createDraft(page.request, `格式校验-${Date.now()}`);
  try {
    await page.goto(`/tasks/${task.id}/edit`);
    await page.locator("#source-file-input").setInputFiles({
      name: "unsupported.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("value\n1\n"),
    });
    await expect(page.getByRole("alert")).toContainText(
      "不支持 unsupported.csv，请上传 PDF、DOCX、Markdown 或 TXT。",
    );
  } finally {
    await page.request.delete(`${api}/tasks/${task.id}`);
  }
});

test("API CORS allows the configured local origin and rejects another origin", async ({
  page,
}) => {
  await page.goto("/tasks");
  const allowed = await page.request.fetch(`${api}/tasks`, {
    method: "OPTIONS",
    headers: {
      Origin: "http://localhost:4173",
      "Access-Control-Request-Method": "GET",
    },
  });
  const denied = await page.request.fetch(`${api}/tasks`, {
    method: "OPTIONS",
    headers: {
      Origin: "https://untrusted.example",
      "Access-Control-Request-Method": "GET",
    },
  });
  expect(allowed.status()).toBe(200);
  expect(allowed.headers()["access-control-allow-origin"]).toBe("http://localhost:4173");
  expect(denied.headers()["access-control-allow-origin"]).toBeUndefined();
});

test("task updates reject a stale version with a stable conflict code", async ({ page }) => {
  const task = await createDraft(page.request, `版本冲突-${Date.now()}`);
  try {
    const response = await page.request.patch(`${api}/tasks/${task.id}`, {
      data: { expected_version: task.version + 1, name: "过期写入" },
    });
    expect(response.status()).toBe(409);
    expect((await response.json()).error.code).toBe("VERSION_CONFLICT");
    const current = await page.request.get(`${api}/tasks/${task.id}`);
    expect((await current.json()).name).toBe(task.name);
    expect((await current.json()).version).toBe(task.version);
  } finally {
    await page.request.delete(`${api}/tasks/${task.id}`);
  }
});

test("cancelled workflow remains cancelled after refresh", async ({ page }) => {
  const task = await createDraft(page.request, `取消验收-${Date.now()}`);
  try {
    const started = await page.request.post(`${api}/tasks/${task.id}/start`);
    expect(started.status()).toBe(202);
    const running = (await started.json()) as { version: number };
    const cancelled = await page.request.post(`${api}/tasks/${task.id}/cancel`, {
      data: { expected_version: running.version },
    });
    expect(cancelled.status()).toBe(202);
    expect((await cancelled.json()).status).toBe("CANCELLED");

    await page.goto(`/tasks/${task.id}/progress`);
    await expect(page.getByText("任务已停止，取消前的进度仍然保留。")).toBeVisible();
    await expect(page.getByRole("button", { name: "取消任务" })).toHaveCount(0);
    await page.reload();
    await expect(page.getByText("任务已停止，取消前的进度仍然保留。")).toBeVisible();
  } finally {
    await page.request.delete(`${api}/tasks/${task.id}`);
  }
});
