// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SessionProvider, useSession } from "./Session";
afterEach(() => { cleanup(); sessionStorage.clear(); vi.unstubAllGlobals(); });
function Probe() {
  const { principal, logout } = useSession();
  return <><span>{principal ? "authenticated" : "anonymous"}</span><button onClick={logout}>logout</button></>;
}
function saved(expiresAt = Date.now() + 60000) { sessionStorage.setItem("finsight.session.v1", JSON.stringify({ token: "test-token", expiresAt })); }
it("restores an unexpired tab session only after checking server identity", async () => {
  saved(); const fetchMock = vi.fn(async (_path: string, _init: RequestInit) => new Response(JSON.stringify({ active: true, user_id: "user", memberships: [] })));
  vi.stubGlobal("fetch", fetchMock);
  render(<SessionProvider><Probe /></SessionProvider>);
  expect(screen.getByRole("status")).toBeTruthy();
  await screen.findByText("authenticated");
  expect(new Headers(fetchMock.mock.calls[0][1].headers).get("Authorization")).toBe("Bearer test-token");
  fireEvent.click(screen.getByText("logout"));
  expect(screen.getByText("anonymous")).toBeTruthy();
  expect(sessionStorage.getItem("finsight.session.v1")).toBeNull();
});
it("drops a revoked saved token after server rejection", async () => {
  saved(); vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 401 })));
  render(<SessionProvider><Probe /></SessionProvider>);
  await screen.findByText("anonymous");
  await waitFor(() => expect(sessionStorage.getItem("finsight.session.v1")).toBeNull());
});
it("discards an expired session without sending it to the server", () => {
  saved(Date.now() - 1000); const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock);
  render(<SessionProvider><Probe /></SessionProvider>);
  expect(screen.getByText("anonymous")).toBeTruthy(); expect(fetchMock).not.toHaveBeenCalled();
});

