import React, { useState } from "react";
import { json } from "../../app/api";
import type { Model } from "../../app/types";

export function ModelModal({
  model,
  onClose,
  onSaved,
}: {
  model?: Model;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    id: model?.id || `model-${Date.now()}`,
    name: model?.name || "新模型",
    model: model?.model || "",
    base_url: model?.base_url || "",
    api_key_env: model?.api_key_env || "OPENAI_API_KEY",
    provider: model?.provider || "openai_compatible",
    enabled: model?.enabled ?? true,
    supports_vision: model?.supports_vision ?? false,
    supports_image_generation: model?.supports_image_generation ?? false,
    supports_video_generation: model?.supports_video_generation ?? false,
    supports_voice_cloning: model?.supports_voice_cloning ?? false,
    video_endpoint: model?.video_endpoint || "",
    video_status_endpoint: model?.video_status_endpoint || "",
    video_content_endpoint: model?.video_content_endpoint || "",
  });
  const editing = Boolean(model);
  const update = (key: string, value: string) =>
    setForm((current) => ({ ...current, [key]: value }));
  const save = () =>
    json(`/api/models${editing ? `/${form.id}` : ""}`, {
      method: editing ? "PATCH" : "POST",
      body: JSON.stringify(form),
    }).then(onSaved);
  return (
    <div className="modal-backdrop">
      <div className="modal">
        <div className="modal-head">
          <h2>{editing ? "编辑模型" : "添加模型"}</h2>
          <button onClick={onClose}>×</button>
        </div>
        {[
          ["name", "模型名称"],
          ["model", "Model ID"],
          ["base_url", "Base URL"],
          ["api_key_env", "API Key 环境变量"],
          ["video_endpoint", "视频创建接口（可选）"],
          ["video_status_endpoint", "视频状态接口（可选）"],
          ["video_content_endpoint", "视频内容接口（可选）"],
        ].map(([key, label]) => (
          <label key={key}>
            {label}
            <input
              value={form[key as keyof typeof form] as string}
              onChange={(event) => update(key, event.target.value)}
            />
          </label>
        ))}
        <label className="model-capability-option">
          <input
            className="model-capability-checkbox"
            type="checkbox"
            checked={form.supports_vision}
            onChange={(event) =>
              setForm((current) => ({
                ...current,
                supports_vision: event.target.checked,
              }))
            }
          />
          <span>支持图片理解</span>
        </label>
        <label className="model-capability-option">
          <input
            className="model-capability-checkbox"
            type="checkbox"
            checked={form.supports_image_generation}
            onChange={(event) =>
              setForm((current) => ({
                ...current,
                supports_image_generation: event.target.checked,
              }))
            }
          />
          <span>支持图片生成</span>
        </label>
        <label className="model-capability-option">
          <input
            className="model-capability-checkbox"
            type="checkbox"
            checked={form.supports_video_generation}
            onChange={(event) =>
              setForm((current) => ({
                ...current,
                supports_video_generation: event.target.checked,
              }))
            }
          />
          <span>支持视频生成</span>
        </label>
        <label className="model-capability-option">
          <input
            className="model-capability-checkbox"
            type="checkbox"
            checked={form.supports_voice_cloning}
            onChange={(event) =>
              setForm((current) => ({
                ...current,
                supports_voice_cloning: event.target.checked,
              }))
            }
          />
          <span>支持声音克隆</span>
        </label>
        <p className="modal-note">
          图片理解、图片生成、视频生成和声音克隆是独立能力，请根据模型实际 API 能力分别勾选。
        </p>
        <div className="modal-actions">
          <button className="secondary-button" onClick={onClose}>
            取消
          </button>
          <button className="primary-button" onClick={save}>
            {editing ? "更新模型" : "添加模型"}
          </button>
        </div>
      </div>
    </div>
  );
}
