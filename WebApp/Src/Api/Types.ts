export type Role = "viewer" | "researcher" | "reviewer" | "workspace_admin";

export interface WorkspaceMembership {
  workspace_id: string;
  role: Role;
  knowledge_base_ids: string[];
}

export interface Principal {
  user_id: string;
  active: boolean;
  memberships: WorkspaceMembership[];
}

export interface LoginResponse {
  access_token: string;
  token_type: "bearer";
  expires_in_seconds: number;
}
