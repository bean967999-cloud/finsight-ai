import { useEffect, useState, type ReactNode } from "react";

export function TechnicalDetails({ children, title = "技术详情" }: { children: ReactNode; title?: string }) {
  return <details className="technical-details"><summary>{title}</summary><div>{children}</div></details>;
}

export function TechnicalValue({ name, value }: { name: string; value: string | number | null | undefined }) {
  const [feedback, setFeedback] = useState("");
  const text = value == null ? "" : String(value);
  useEffect(() => { setFeedback(""); }, [text]);
  async function copy() {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("clipboard_unavailable");
      await navigator.clipboard.writeText(text);
      setFeedback("已复制");
    } catch { setFeedback("复制失败，请手动选择并复制编号。"); }
  }
  return <div className="technical-value"><span>{name}：</span><code>{text || "未记录"}</code>
    {text && <button type="button" onClick={() => void copy()} aria-label={`复制${name}`}>复制</button>}
    {feedback && <span role="status">{feedback}</span>}
  </div>;
}

// A neutral short identifier, not a fabricated workspace name. Full IDs remain available.
export function workspaceLabel(id: string): string {
  return `工作空间 ${id.length > 16 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id}`;
}

export function ErrorNotice({ message }: { message: string }) {
  const match = /\s请求编号：([A-Za-z0-9-]+)$/.exec(message);
  return <><p className="error" role="alert">{match ? message.slice(0, match.index) : message}</p>
    {match && <TechnicalDetails title="错误诊断"><TechnicalValue name="请求编号" value={match[1]} /></TechnicalDetails>}</>;
}
