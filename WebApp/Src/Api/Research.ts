import type { Citation } from "./Evidence";

export interface ResearchRequest {
  query: string;
  workspace_id: string;
  knowledge_base_id?: string;
  prices?: number[];
  release_requested: boolean;
}

export interface RiskMetrics {
  observations: number;
  cumulative_return: number;
  annualized_volatility: number;
  max_drawdown: number;
  historical_var: number;
  historical_cvar: number;
  sharpe_ratio: number | null;
}

export interface GenerationInfo {
  mode: "local" | "generated" | "fallback";
  reason: string;
  attempts: number;
}

export interface ResearchResponse {
  thread_id: string | null;
  review_pending: boolean;
  review_request: Record<string, unknown> | null;
  intent: string;
  answer: string;
  answer_status: "answered" | "insufficient_evidence" | "refused";
  limitations: string[];
  risk_metrics: RiskMetrics | null;
  evidence: string[];
  citations?: Citation[];
  generation?: GenerationInfo | null;
}

export function generationLabel(result: { generation?: GenerationInfo | null }): string | null {
  if (!result.generation) return null;
  if (result.generation.mode === "generated") return "回答方式：模型选择已核验证据，本地模板呈现（非自由生成）";
  if (result.generation.mode === "fallback") return "回答方式：外部调用未形成合格结果，已回退至本地核验答案";
  if (result.generation.mode === "local") return "回答方式：本地核验答案，未发送外部请求";
  return "回答方式：未识别的调用状态，不能据此判断外部调用是否成功。";
}

export function parsePrices(input: string): number[] | undefined {
  if (!input.trim()) return undefined;
  const parts = input.split(/[，,\s]+/).filter(Boolean);
  if (parts.length < 3 || parts.length > 10000) {
    throw new Error("价格序列需要 3 至 10000 个数值。");
  }
  const values = parts.map(Number);
  if (values.some((value) => !Number.isFinite(value) || value <= 0)) {
    throw new Error("价格必须是大于零的有限数值。");
  }
  return values;
}

export function resultLabel(result: ResearchResponse): string {
  if (result.review_pending) return "等待人工确认 · 尚未对外定稿";
  if (result.answer_status === "insufficient_evidence") return "证据不足 · 不形成结论";
  if (result.answer_status === "refused") return "无法回答";
  return "已生成研究结果";
}
