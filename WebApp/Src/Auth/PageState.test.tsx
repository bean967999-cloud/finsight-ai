// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { PageStateProvider, usePageState } from "./PageState";
afterEach(cleanup);
function Draft() {
  const [text, setText] = usePageState("draft", "");
  const [result, setResult] = usePageState("result", 0);
  return <><input aria-label="draft" value={text} onChange={event => setText(event.target.value)} />
    <button onClick={() => { setResult(n => n + 1); setResult(n => n + 1); }}>Compute</button><span>Result:{result}</span></>;
}
it("restores inputs and results after navigation and clears them for another session", () => {
  const view = render(<PageStateProvider key="account1"><Draft /></PageStateProvider>);
  fireEvent.change(screen.getByLabelText("draft"), { target: { value: "saved question" } });
  fireEvent.click(screen.getByText("Compute"));
  view.rerender(<PageStateProvider key="account1"><p>Another page</p></PageStateProvider>);
  view.rerender(<PageStateProvider key="account1"><Draft /></PageStateProvider>);
  expect((screen.getByLabelText("draft") as HTMLInputElement).value).toBe("saved question");
  expect(screen.getByText("Result:2")).toBeTruthy();
  view.rerender(<PageStateProvider key="account2"><Draft /></PageStateProvider>);
  expect((screen.getByLabelText("draft") as HTMLInputElement).value).toBe("");
  expect(screen.getByText("Result:0")).toBeTruthy();
});
