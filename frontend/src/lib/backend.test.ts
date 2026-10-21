import { afterEach, describe, expect, it, vi } from "vitest";

async function load(url: string) {
  vi.stubEnv("VITE_BACKEND_URL", url);
  vi.resetModules();
  return import("./backend");
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("backend URLs", () => {
  it("stays on the same origin in development (Vite proxies /api and /ws)", async () => {
    const { apiUrl, wsUrl } = await load("");
    expect(apiUrl("/api/eval")).toBe("/api/eval");
    expect(wsUrl("/ws/call")).toBe(`ws://${location.host}/ws/call`);
  });

  it("points at the hosted backend, with wss for an https backend", async () => {
    const { apiUrl, wsUrl } = await load(" https://tenor-api.up.railway.app/ ");
    expect(apiUrl("/api/calls")).toBe("https://tenor-api.up.railway.app/api/calls");
    expect(wsUrl("/ws/health")).toBe("wss://tenor-api.up.railway.app/ws/health");
  });
});
