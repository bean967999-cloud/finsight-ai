export interface EvaluationOverview {
  retrieval_run?: { run_id: string; executed_at: string; source: string; knowledge_base_id: string } | null;
  generated_at: string;
  execution: "local_synthetic_recomputed_on_request";
  research: {
    suite_name: string;
    suite_version: string;
    source: "synthetic_fixture";
    metrics: {
      tool_case_count: number;
      intent_accuracy: number;
      tool_set_accuracy: number;
      limitation_accuracy: number;
      tool_case_pass_rate: number;
      numeric_case_count: number;
      numeric_metric_count: number;
      numeric_metric_pass_rate: number;
      numeric_case_pass_rate: number;
    };
    tool_cases: {
      case_id: string;
      intent_correct: boolean;
      tool_set_correct: boolean;
      limitation_correct: boolean;
      passed: boolean;
      failure_reasons: string[];
    }[];
    numeric_cases: {
      case_id: string;
      passed: boolean;
      metrics: {
        metric: string;
        expected: number;
        observed: number | null;
        absolute_tolerance: number;
        absolute_error: number | null;
        passed: boolean;
        failure_reason: string | null;
      }[];
    }[];
  };
  retrieval: {
    dataset_name: string;
    dataset_version: string;
    suite_name: string | null;
    suite_version: string | null;
    status: "not_run" | "observations_scored";
    metrics: {
      question_count: number;
      answerable_count: number;
      refusal_count: number;
      retrieval_recall_at_k: number;
      rerank_hit_rate_at_n: number;
      citation_correctness: number;
      refusal_accuracy: number;
      mean_latency_ms: number;
    } | null;
    unrun_question_ids: string[];
    cases?: {
      question_id: string; should_refuse: boolean; passed: boolean; refused: boolean;
      retrieval_rank: number | null; rerank_rank: number | null;
      citation_correct: boolean; failure_reasons: string[];
    }[];
  };
}

export function evaluatedCount(passed: number, total: number): string {
  return `${passed} / ${total}`;
}

export function rate(value: number | null): string {
  return value === null ? "未运行" : `${(value * 100).toFixed(1)}%`;
}
