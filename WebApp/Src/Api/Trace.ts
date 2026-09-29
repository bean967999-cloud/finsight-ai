export interface ResearchTraceSnapshot {
  request_id: string;
  workspace_id: string;
  owner_user_id: string;
  knowledge_base_id: string | null;
  truncated: boolean;
  frames: {
    sequence: number;
    occurred_at: string;
    event: {
      kind: string;
      intent: string | null;
      planned_tools: string[];
      tool: string | null;
      tool_status: string | null;
      duration_ms: number | null;
      error_code: string | null;
      answer_status: string | null;
      review_pending: boolean | null;
      thread_id: string | null;
      review_choice: string | null;
      status_code: number | null;
    };
  }[];
}
