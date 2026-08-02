from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Workspace(BaseModel):
    id: str
    name: str
    root_path: str
    description: str = ""
    created_at: str
    updated_at: str


class Task(BaseModel):
    id: str
    workspace_id: str
    title: str
    status: str = "queued"
    permission_mode: str = "workspace"
    model_id: str = "demo"
    current_state: str = "等待输入"
    selected_skill_ids: list[str] = Field(default_factory=list)
    selected_expert_ids: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class ModelConfig(BaseModel):
    id: str
    name: str
    provider: str = "openai_compatible"
    model: str
    base_url: str = ""
    api_key_env: str = ""
    enabled: bool = True
    supports_vision: bool = False
    supports_image_generation: bool = False
    is_default: bool = False


class CreateWorkspace(BaseModel):
    name: str
    root_path: str
    description: str = ""


class CreateTask(BaseModel):
    workspace_id: str
    title: str = "新任务"
    permission_mode: str = "workspace"
    model_id: str = "demo"


class MessageRequest(BaseModel):
    content: str = Field(min_length=1)
    workspace_id: str
    permission_mode: str = "workspace"
    model_id: str = "demo"
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class TaskCapabilities(BaseModel):
    selected_skill_ids: list[str] = Field(default_factory=list)
    selected_expert_ids: list[str] = Field(default_factory=list)


class ApprovalDecision(BaseModel):
    approved: bool


class MCPConfig(BaseModel):
    id: str
    name: str
    transport: str = "stdio"
    command: str = ""
    args: list[str] = []
    url: str = ""
    enabled: bool = False
    allowed_tools: list[str] = []
    env: dict[str, str] = {}
    headers: dict[str, str] = {}


class MemoryRequest(BaseModel):
    workspace_id: str
    category: str = "preference"
    content: str
    confidence: float = 0.8


class SkillHubInstallRequest(BaseModel):
    coordinate: str = Field(min_length=1, max_length=200)
    version: str = ""
