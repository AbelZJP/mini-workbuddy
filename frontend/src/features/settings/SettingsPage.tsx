import React, { useEffect, useState } from "react";
import {
  api,
  json,
  loadCapabilities,
  loadCapabilityModels,
  updateCapabilityModel,
} from "../../app/api";
import type {
  Capability,
  CapabilityModelOption,
  Memory,
  Model,
} from "../../app/types";
import { EmptyCard } from "../../components/common";
import { ModelModal } from "./SettingsParts";

export function SettingsPage({
  models,
  refresh,
}: {
  models: Model[];
  refresh: () => void;
}) {
  const [tab, setTab] = useState("models");
  const [editingModel, setEditingModel] = useState<Model | null | undefined>(
    undefined,
  );
  const [memories, setMemories] = useState<Memory[]>([]);
  const [capabilities, setCapabilities] = useState<Capability[]>([]);
  const [capabilityModels, setCapabilityModels] = useState<
    Record<string, CapabilityModelOption[]>
  >({});
  useEffect(() => {
    if (tab === "memory") json<Memory[]>("/api/memory").then(setMemories);
    if (tab === "models") {
      void loadCapabilities().then(async (result) => {
        setCapabilities(result.items);
        const entries = await Promise.all(
          result.items.map(async (item) => [
            item.id,
            await loadCapabilityModels(item.id),
          ] as const),
        );
        setCapabilityModels(Object.fromEntries(entries));
      });
    }
  }, [tab]);
  const removeModel = async (model: Model) => {
    if (model.id === "demo") return;
    if (window.confirm(`删除模型“${model.name}”？`)) {
      await api(`/api/models/${model.id}`, { method: "DELETE" });
      refresh();
    }
  };
  const makeDefault = async (model: Model) => {
    try {
      await api(`/api/models/${model.id}/default`, { method: "POST" });
      refresh();
    } catch (e) {
      window.alert(`设置默认模型失败：${String(e)}`);
    }
  };
  return (
    <section className="settings">
      <header className="topbar">
        <div>
          <span className="eyebrow">PREFERENCES</span>
          <h1>设置</h1>
          <p>配置模型、权限和上下文工程。</p>
        </div>
      </header>
      <div className="settings-layout">
        <div className="settings-menu">
          <button
            className={tab === "models" ? "selected" : ""}
            onClick={() => setTab("models")}
          >
            模型配置
          </button>
          <button
            className={tab === "permissions" ? "selected" : ""}
            onClick={() => setTab("permissions")}
          >
            默认权限
          </button>
          <button
            className={tab === "memory" ? "selected" : ""}
            onClick={() => setTab("memory")}
          >
            上下文与记忆
          </button>
          <button
            onClick={() =>
              alert("本地 SQLite 数据库：.mini-workbuddy/workbuddy.sqlite3")
            }
          >
            数据管理
          </button>
          <button onClick={() => alert("日志将在任务执行时写入后端控制台")}>
            日志与调试
          </button>
        </div>
        <div className="settings-content">
          {tab === "models" && (
            <div className="setting-section">
              <div>
                <h2>已配置模型</h2>
                <p>模型配置持久化到 SQLite；API Key 通过环境变量读取。</p>
              </div>
              <button
                className="dashed-button model-add-button"
                onClick={() => setEditingModel(null)}
              >
                ＋ 添加模型
              </button>
              {models.map((model) => (
                <div className="model-row" key={model.id}>
                  <div className="model-badge">◉</div>
                  <div>
                    <b>{model.name}</b>
                    <span>{model.model}</span>
                  </div>
                  <span className="model-status">
                    {model.is_default
                      ? "默认"
                      : model.id === "demo"
                        ? "演示"
                        : "已配置"}
                  </span>
                  {!model.is_default && (
                    <button
                      className="text-button"
                      onClick={() => makeDefault(model)}
                    >
                      设为默认
                    </button>
                  )}
                  <button
                    className="text-button"
                    onClick={() => setEditingModel(model)}
                  >
                    编辑
                  </button>
                  {model.id !== "demo" && (
                    <button
                      className="danger-button"
                      onClick={() => removeModel(model)}
                    >
                      删除
                    </button>
                  )}
                </div>
              ))}
              <div className="capability-models">
                <h2>能力模型路由</h2>
                <p>
                  会话继续使用右下角的主模型；图片生成等专项能力按这里的策略自动选择模型。
                </p>
                {capabilities.map((capability) => (
                  <div className="capability-model-row" key={capability.id}>
                    <div>
                      <b>{capability.name}</b>
                      <small>{capability.description}</small>
                    </div>
                    <select
                      value={capability.configured_model_id || ""}
                      onChange={(event) => {
                        void updateCapabilityModel(
                          capability.id,
                          event.target.value,
                        ).then(() => loadCapabilities().then((result) => setCapabilities(result.items)));
                      }}
                    >
                      <option value="">自动选择</option>
                      {(capabilityModels[capability.id] || []).map((option) => (
                        <option value={option.id} key={option.id}>
                          {option.name}
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>
            </div>
          )}
          {tab === "permissions" && (
            <div className="setting-section">
              <h2>默认权限</h2>
              <p>新任务默认使用工作区写权限，高风险操作仍应在 Agent 层审批。</p>
              {["只读", "可修改工作区", "允许执行命令", "完全自主"].map(
                (item, index) => (
                  <div className="preference-row" key={item}>
                    <span>
                      <b>{item}</b>
                      <small>
                        {index === 0 ? "仅允许读取和分析" : "权限档位"}
                      </small>
                    </span>
                    <input
                      type="radio"
                      name="permission"
                      defaultChecked={index === 1}
                    />
                  </div>
                ),
              )}
            </div>
          )}
          {tab === "memory" && (
            <div className="setting-section">
              <h2>长期记忆</h2>
              <p>来自任务的可编辑记忆，保存于 SQLite。</p>
              {memories.length === 0 && (
                <EmptyCard text="暂无长期记忆。你可以在对话中说“记住我偏好……”后接入自动提取。" />
              )}
              {memories.map((memory) => (
                <div className="preference-row" key={memory.id}>
                  <span>
                    <b>{memory.category}</b>
                    <small>{memory.content}</small>
                  </span>
                  <button
                    className="text-button"
                    onClick={() =>
                      api(`/api/memory/${memory.id}`, {
                        method: "DELETE",
                      }).then(() =>
                        setMemories((items) =>
                          items.filter((item) => item.id !== memory.id),
                        ),
                      )
                    }
                  >
                    删除
                  </button>
                </div>
              ))}
            </div>
          )}
          {editingModel !== undefined && (
            <ModelModal
              model={editingModel || undefined}
              onClose={() => setEditingModel(undefined)}
              onSaved={() => {
                setEditingModel(undefined);
                refresh();
              }}
            />
          )}
        </div>
      </div>
    </section>
  );
}
