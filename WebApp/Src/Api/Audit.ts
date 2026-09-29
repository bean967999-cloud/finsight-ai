export interface AuditRecord {
  request_id: string;
  action: string;
  method: string;
  route_pattern: string;
  actor_user_id: string | null;
  workspace_id: string;
  outcome: string;
  status_code: number | null;
  started_at: string;
  finished_at: string | null;
}

export interface AuditPage {
  workspace_id: string;
  records: AuditRecord[];
  offset: number;
  limit: number;
  has_more: boolean;
}

export function auditOutcome(outcome: string): string {
  const labels: Record<string, string> = {
    started: "已开始 · 尚未记录完成", succeeded: "操作成功", denied: "访问被拒绝", failed: "操作失败",
  };
  return labels[outcome] ?? outcome;
}
