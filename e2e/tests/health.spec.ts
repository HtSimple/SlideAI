import { expect, test } from '@playwright/test'

test('task center loads and reports API readiness', async ({ page }) => {
  await page.goto('/tasks')

  await expect(page.getByRole('heading', { name: '任务中心' })).toBeVisible()
  await expect(page.getByRole('status')).toHaveText('服务已就绪')
  await page.screenshot({ path: 'test-results/task-center.png', fullPage: true })
})
