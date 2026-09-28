import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import HealthStatus from "../src/components/HealthStatus.vue";
import { getHealth } from "../src/api/health";

vi.mock("../src/api/health", () => ({
  getHealth: vi.fn(),
}));

describe("health status", () => {
  beforeEach(() => {
    vi.mocked(getHealth).mockReset();
  });

  it("healthClientDisplaysApiStatus", async () => {
    vi.mocked(getHealth).mockResolvedValue({ status: "ready" });

    const wrapper = mount(HealthStatus);
    await flushPromises();

    expect(getHealth).toHaveBeenCalledOnce();
    expect(wrapper.get('[role="status"]').text()).toContain("服务已就绪");
  });
});
