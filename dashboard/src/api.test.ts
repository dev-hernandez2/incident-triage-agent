import { describe, expect, it, vi } from "vitest";
import { approveAction, fetchIncident, fetchIncidents, rejectAction } from "./api";

describe("fetchIncidents", () => {
  it("returns the parsed incident list", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{ id: "1", alertname: "PodCrashLooping", status: "received" }],
    });
    vi.stubGlobal("fetch", mockFetch);

    const incidents = await fetchIncidents("http://api.test");

    expect(incidents).toEqual([
      { id: "1", alertname: "PodCrashLooping", status: "received" },
    ]);
    expect(mockFetch).toHaveBeenCalledWith("http://api.test/incidents", {
      credentials: "include",
    });
  });
});

describe("fetchIncident", () => {
  it("returns the parsed incident detail", async () => {
    const detail = {
      id: "1",
      alertname: "PodCrashLooping",
      status: "received",
      findings: [],
      timeline: [],
    };
    const mockFetch = vi.fn().mockResolvedValue({ ok: true, json: async () => detail });
    vi.stubGlobal("fetch", mockFetch);

    const result = await fetchIncident("http://api.test", "1");

    expect(result).toEqual(detail);
  });
});

describe("approveAction", () => {
  it("posts to the approve endpoint and throws on a 403", async () => {
    const mockFetch = vi.fn().mockResolvedValue({ ok: false, status: 403 });
    vi.stubGlobal("fetch", mockFetch);

    await expect(approveAction("http://api.test", "action-1")).rejects.toThrow();
    expect(mockFetch).toHaveBeenCalledWith("http://api.test/actions/action-1/approve", {
      method: "POST",
      credentials: "include",
    });
  });
});

describe("rejectAction", () => {
  it("posts the reason in the request body", async () => {
    const mockFetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "rejected" }) });
    vi.stubGlobal("fetch", mockFetch);

    await rejectAction("http://api.test", "action-1", "too risky");

    expect(mockFetch).toHaveBeenCalledWith("http://api.test/actions/action-1/reject", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: "too risky" }),
    });
  });
});
