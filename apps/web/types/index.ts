export type User = {
  id: string;
  name: string;
  email: string;
  role: string;
  agency: Agency;
};

export type Agency = { id: string; name: string; slug: string; brand_color: string; logo_url: string | null };

export type AgentSummary = { id: string; name: string; description: string; is_active: boolean };

export type Client = {
  id: string;
  name: string;
  industry: string;
  description: string;
  general_context: string;
  is_active: boolean;
  portal_slug: string;
  portal_enabled: boolean;
  portal_title: string;
  portal_domain: string | null;
  portal_domain_verified: boolean;
  logo_url: string | null;
  agents: AgentSummary[];
  created_at: string;
  updated_at: string;
};

export type PortalUser = {
  id: string;
  name: string;
  email: string;
  is_active: boolean;
  devices: number;
  // null means this person sees every conversation of the client, which is
  // what a supervisor needs.
  department_id: string | null;
  department_name: string | null;
  created_at: string;
};

export type Department = {
  id: string;
  client_id: string;
  agent_id: string;
  agent_name: string | null;
  name: string;
  slug: string;
  description: string;
  is_entry: boolean;
  enabled: boolean;
  position: number;
  // Solo viene poblada en la respuesta de creación/reenvío (y, más adelante,
  // en la lectura de la lista): null cuando nunca se invitó a nadie a esta
  // dependencia, o cuando la última invitación ya fue aceptada.
  invitation?: InvitationOut | null;
};

// Espejo de InvitationOut en apps/api/app/schemas.py.
export type InvitationOut = {
  id: string;
  email: string;
  expires_at: string;
  delivery: "sent" | "manual" | "failed";
  // Solo viaja cuando delivery === "manual": con e-mail activo queda
  // explícitamente en null para que el frontend tenga una sola rama.
  accept_url: string | null;
};

export type PortalInvitationAccept = { token: string; password: string };

export type PortalSession = {
  client_id: string;
  client_name: string;
  portal_slug: string;
  agency_name: string;
  user_id: string | null;
  user_name: string | null;
};

export type ClientDomain = {
  domain: string | null;
  verified: boolean;
  txt_host: string | null;
  txt_value: string | null;
};

export type Agent = {
  id: string;
  client_id: string;
  provider: string;
  name: string;
  description: string;
  instructions: string;
  personality: string;
  brief_summary: string;
  brief_products: string;
  brief_audience: string;
  brief_policies: string;
  brief_goal: string;
  brief_dos: string;
  brief_donts: string;
  model: string;
  timezone: string;
  manual_context: string;
  temperature: number;
  max_tokens: number;
  memory_limit: number;
  image_enabled: boolean;
  image_model: string;
  audio_enabled: boolean;
  audio_model: string;
  widget_enabled: boolean;
  widget_public_id: string;
  widget_greeting: string;
  widget_color: string;
  widget_position: string;
  is_active: boolean;
  client: Client;
  created_at: string;
  updated_at: string;
};

export type Provider = {
  provider: string;
  label: string;
  configured: boolean;
  api_key_masked: string;
};

export type ProviderTest = { ok: boolean; message: string; models: string[] };

export type KnowledgeDocument = {
  id: string;
  filename: string;
  status: "processed" | "error" | "pending";
  error_message: string | null;
  character_count: number;
  created_at: string;
};

export type QAPair = { id: string; question: string; answer: string };

export type ToolParam = { name: string; type: "string" | "number" | "integer" | "boolean"; description: string; required: boolean };
export type McpCachedTool = { name: string; description: string; input_schema?: Record<string, unknown> };
export type AgentTool = {
  id: string;
  agent_id: string;
  type: "http" | "mcp";
  name: string;
  description: string;
  enabled: boolean;
  url: string;
  http_method: string;
  prompt_instructions: string;
  body_params: ToolParam[];
  query_params: ToolParam[];
  timeout_seconds: number;
  transport: "sse" | "streamable_http";
  cached_tools: McpCachedTool[];
  tools_cached_at: string | null;
  has_headers: boolean;
  created_at: string;
  updated_at: string;
};
export type ToolCallMeta = { name: string; arguments: Record<string, unknown>; result_preview: string; is_error: boolean };

export type Source = { id: string; filename: string; excerpt: string };
export type Attachment = { id: string; kind: "image" | "audio" | "video" | "file"; mime: string; filename: string | null; size_bytes: number };
export type Message = { id: string; role: "user" | "assistant" | "system"; kind?: "message" | "activity"; delivery_status?: "sent" | "delivered" | "read" | "failed" | null; delivery_error?: string | null; activity?: { event: string; hours?: number | string; assignee?: string; from?: string } | null; content: string; sources: Source[]; tool_calls?: ToolCallMeta[] | null; sender_type: "visitor" | "ai" | "human"; sender_name: string | null; reaction?: string | null; quoted_message_id?: string | null; created_at: string; attachments?: Attachment[] };

export type ConversationInbox = {
  id: string;
  agent_id: string;
  agent_name: string;
  client_id: string;
  title: string;
  contact_name: string | null;
  channel: string;
  mode: "ai" | "human";
  preview: string;
  unread: boolean;
  unread_count: number;
  updated_at: string;
};
export type Conversation = {
  id: string;
  client_id: string;
  agent_id: string;
  title: string;
  mode: "ai" | "human";
  status?: "open" | "resolved";
  resolved_at?: string | null;
  first_reply_at?: string | null;
  taken_over_at?: string | null;
  waiting_since?: string | null;
  assignee_id?: string | null;
  assignee_name?: string | null;
  department_id?: string | null;
  department_name?: string | null;
  reply_window_until?: string | null;
  reply_window_open?: boolean;
  channel: string;
  external_chat_id: string | null;
  contact_name: string | null;
  contact_id?: string | null;
  created_at: string;
  updated_at: string;
  preview?: string;
  unread?: boolean;
  unread_count?: number;
  messages?: Message[];
};

export type WhatsAppChannel = {
  id: string;
  client_id: string;
  agent_id: string;
  status: "disconnected" | "connecting" | "qr" | "connected" | "reconnecting" | "error";
  phone_number: string | null;
  display_name: string | null;
  qr_code: string | null;
  last_error: string | null;
  is_enabled: boolean;
  has_session: boolean;
  last_connected_at: string | null;
  created_at: string;
  updated_at: string;
};

export type WhatsAppCloudChannel = {
  id: string;
  client_id: string;
  agent_id: string;
  status: "disconnected" | "connected" | "error";
  phone_number: string | null;
  display_name: string | null;
  phone_number_id: string;
  waba_id: string | null;
  has_access_token: boolean;
  has_app_secret: boolean;
  webhook_url: string;
  webhook_verify_token: string;
  last_error: string | null;
  is_enabled: boolean;
  last_connected_at: string | null;
  created_at: string;
  updated_at: string;
};

export type Template = {
  id: string | null;
  name: string;
  language: string;
  category: string;
  status: "APPROVED" | "PENDING" | "REJECTED" | string;
  body: string;
  footer: string;
  variables: number;
  rejected_reason: string | null;
};

export type PortalChannel = {
  channel: "whatsapp" | "whatsapp_cloud";
  status: string;
  phone_number: string | null;
  display_name: string | null;
  supports_templates: boolean;
};

export type Contact = {
  id: string;
  name: string;
  phone: string | null;
  email: string | null;
  notes: string;
  created_at: string;
  updated_at: string;
  conversation_count: number;
  open_count: number;
  last_activity_at: string | null;
};

// Espejo de ErrorEventOut en apps/api/app/schemas.py.
export type ErrorEvent = {
  id: string;
  occurred_at: string;
  source: string;
  capture_kind: string;
  exception_type: string;
  message: string;
  traceback: string | null;
  request_method: string | null;
  request_path: string | null;
  subject_ref: string | null;
  // true cuando la fila no tiene agency_id (no derivable): visible para
  // cualquier persona autenticada, no solo para la agencia dueña.
  is_global: boolean;
};

export type ReadinessCheck = {
  status: "ok" | "degraded";
  checks: { database: "ok" | "error" };
};

export type PortalPublic = {
  client_name: string;
  portal_title: string;
  portal_slug: string;
  agency_name: string;
  agency_brand_color: string;
  agency_logo_url: string | null;
  client_logo_url: string | null;
};
