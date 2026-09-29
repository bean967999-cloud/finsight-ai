import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, requestFailure, requestJson } from "./Client";

afterEach(() => vi.unstubAllGlobals());

describe("requestJson", () => {
  it.each([[403, "授权"], [404, "编号"], [409, "冲突"], [429, "勿连续重复提交"], [500, "勿直接重复提交"]])
    ("gives safe next steps for POST status %s without displaying server bodies", async (status, expected) => {
      const fetchMock = vi.fn().mockResolvedValue(new Response("private backend error body", {
        status, headers: { "X-Request-ID": "request-fixture" },
      }));
      vi.stubGlobal("fetch", fetchMock);
      try {
        await requestJson("/api/v1/agent/query", "POST", { body: {} });
        throw new Error("expected rejection");
      } catch (error) {
        expect(error).toBeInstanceOf(ApiError);
        expect((error as ApiError).message).toContain(expected);
        expect((error as ApiError).message).not.toContain("private backend error body");
        expect(requestFailure(error, "failed")).toContain("请求编号：request-fixture");
      }
      expect(fetchMock).toHaveBeenCalledOnce();
    });
  it("does not suggest resubmission after a POST network failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("internal connection data")));
    await expect(requestJson("/api/v1/jobs", "POST", { body: {} })).rejects.toThrow("勿直接重复提交");
  });
  it("treats malformed successful POST responses as uncertain outcomes", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("invalid-json", { status: 200 })));
    await expect(requestJson("/api/v1/jobs", "POST", { body: {} })).rejects.toThrow("无法确认提交结果");
  });
  it("adds the session token only when provided", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), {
      status: 200, headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    await requestJson("/api/v1/auth/me", "GET", { token: "session-token" });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer session-token");
  });

  it("clears a rejected session and preserves the request id", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", {
      status: 401, headers: { "X-Request-ID": "req-17" },
    })));
    const onUnauthorized = vi.fn();

    await expect(requestJson("/api/v1/auth/me", "GET", {
      token: "expired", onUnauthorized,
    })).rejects.toMatchObject({ status: 401, requestId: "req-17" });
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("does not display an internal server error body", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("database connection string", {
      status: 500,
    })));
    await expect(requestJson("/api/v1/query/structured", "POST", { body: {} }))
      .rejects.toThrow("服务处理异常，提交结果可能不确定。请先核查研究、任务或审核状态，勿直接重复提交。");
  });

  it("exposes the successful response request id for correlation", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", {
      status: 200, headers: { "X-Request-ID": "req-18" },
    })));
    const onRequestId = vi.fn();
    await requestJson("/api/v1/evidence/search", "POST", { body: {}, onRequestId });
    expect(onRequestId).toHaveBeenCalledWith("req-18");
  });
});
