export type Workspace = {
  id: string;
  name: string;
  root_path: string;
  description?: string;
};
export type Task = {
  id: string;
  workspace_id: string;
  title: string;
  status: string;
  current_state: string;
  model_id: string;
  selected_skill_ids?: string[];
  selected_expert_ids?: string[];
};
export type ToolLog = {
  id: string;
  name: string;
  kind?: "skill" | "mcp" | "tool" | string;
  status?: string;
  input?: unknown;
  output?: string;
  label?: string;
  artifact_path?: string;
};
export type ApprovalCall = { id: string; name: string; input?: unknown };
export type Approval = {
  id: string;
  message?: string;
  tool_calls: ApprovalCall[];
  status?: "pending" | "approved" | "rejected";
};
export type Message = {
  role: "user" | "assistant";
  content: string;
  type?: string;
  metadata?: { tool_logs?: ToolLog[]; approvals?: Approval[] };
};
export type Attachment = {
  name: string;
  path: string;
  size: number;
  content_type?: string;
};
export type Model = {
  id: string;
  name: string;
  provider?: string;
  model: string;
  base_url?: string;
  api_key_env?: string;
  enabled?: boolean;
  supports_vision?: boolean;
  supports_image_generation?: boolean;
  supports_video_generation?: boolean;
  supports_voice_cloning?: boolean;
  video_endpoint?: string;
  video_status_endpoint?: string;
  video_content_endpoint?: string;
  is_default?: boolean;
};
export type Capability = {
  id: string;
  name: string;
  description: string;
  model_capability: string;
  output_type: string;
  available: boolean;
  model_id: string;
  model_name: string;
  configured_model_id?: string;
};
export type CapabilityModelOption = {
  id: string;
  name: string;
  model: string;
};
export type Skill = {
  id: string;
  name: string;
  description: string;
  path: string;
  enabled: boolean;
  scope?: "app_global" | "workspace" | string;
  content?: string;
};
export type SkillHubSkill = {
  id: string;
  slug: string;
  namespace?: string;
  name: string;
  description: string;
  labels?: string[];
  downloads?: number;
  rating?: number;
  starCount?: number;
  latestVersion?: string;
  updatedAt?: string;
  installed?: boolean;
  source?: string;
};
export type SkillHubRanking = {
  id: string;
  name: string;
  description?: string;
};
export type Mcp = {
  id: string;
  name: string;
  transport: string;
  command?: string;
  args?: string[];
  url?: string;
  enabled: boolean;
  allowed_tools?: string[];
  env?: Record<string, string>;
  headers?: Record<string, string>;
};
export type Memory = {
  id: string;
  workspace_id: string;
  category: string;
  content: string;
  confidence: number;
};
export type Expert = {
  id: string;
  name: string;
  description: string;
  department: string;
  catalog_path: string;
  installed: boolean;
  enabled?: boolean;
  source?: string;
  updated_at?: string;
};
export type ExpertResponse = {
  items: Expert[];
  departments: string[];
  synced: boolean;
  repository: string;
};
export type CanvasNodeKind =
  | "text"
  | "image-upload"
  | "ai-image"
  | "video-upload"
  | "ai-video"
  | "voice-clone"
  | "note";
export type CanvasGraph = {
  nodes: Array<{
    id: string;
    type: CanvasNodeKind;
    position: { x: number; y: number };
    data: Record<string, unknown>;
  }>;
  edges: Array<Record<string, unknown>>;
  viewport: { x: number; y: number; zoom: number };
};
export type CanvasProject = {
  id: string;
  workspace_id: string;
  name: string;
  graph: CanvasGraph;
  created_at: string;
  updated_at: string;
};
export type Run = {
  id: string;
  task_id: string;
  status: string;
  current_step?: string;
  error?: string;
  cancel_requested?: boolean;
  started_at?: string;
  finished_at?: string;
};
