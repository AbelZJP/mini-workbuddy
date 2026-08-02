import React, { useState } from "react";
import { json } from "../../app/api";
import type { Workspace } from "../../app/types";

export function CreateWorkspaceModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (item: Workspace) => void;
}) {
  const [name, setName] = useState("新工作空间");
  const [rootPath, setRootPath] = useState("");
  const [saving, setSaving] = useState(false);
  const [picking, setPicking] = useState(false);
  const [error, setError] = useState("");
  const pickDirectory = async () => {
    setPicking(true);
    setError("");
    try {
      const picked = await json<{
        cancelled: boolean;
        path: string;
        name: string;
      }>("/api/system/pick-directory", { method: "POST" });
      if (!picked.cancelled && picked.path) {
        setRootPath(picked.path);
        if (!name.trim() || name === "新工作空间") setName(picked.name);
      }
    } catch (e) {
      setError(String(e).replace(/^Error:\s*/, ""));
    } finally {
      setPicking(false);
    }
  };
  const create = async () => {
    if (!rootPath.trim()) {
      setError("请选择或输入本机文件夹完整路径");
      return;
    }
    setSaving(true);
    setError("");
    try {
      onCreated(
        await json<Workspace>("/api/workspaces", {
          method: "POST",
          body: JSON.stringify({
            name: name || rootPath.split("/").pop(),
            root_path: rootPath.trim(),
          }),
        }),
      );
    } catch (e) {
      setError(String(e));
      setSaving(false);
    }
  };
  return (
    <div className="modal-backdrop">
      <div className="modal">
        <div className="modal-head">
          <h2>创建工作空间</h2>
          <button onClick={onClose}>×</button>
        </div>
        <label>
          名称
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label>
          本机文件夹完整路径
          <div className="workspace-path-row">
            <input
              value={rootPath}
              onChange={(event) => setRootPath(event.target.value)}
              placeholder="例如 /Users/你的用户名/Documents/project"
            />
            <button
              type="button"
              className="secondary-button workspace-path-button"
              disabled={picking || saving}
              onClick={() => void pickDirectory()}
            >
              {picking ? "打开中…" : "选择文件夹"}
            </button>
          </div>
        </label>
        <p className="modal-note">
          工作空间直接绑定这个本机文件夹，不会复制文件。点击“选择文件夹”后，由本机
          Python 后端打开系统选择器并回填绝对路径。
        </p>
        {error && <p className="modal-error">{error}</p>}
        <div className="modal-actions">
          <button className="secondary-button" onClick={onClose}>
            取消
          </button>
          <button
            className="primary-button"
            disabled={!rootPath.trim() || saving}
            onClick={create}
          >
            {saving ? "创建中…" : "创建工作空间"}
          </button>
        </div>
      </div>
    </div>
  );
}
export function WorkspaceModal({
  workspace,
  onClose,
  onSaved,
}: {
  workspace: Workspace;
  onClose: () => void;
  onSaved: (item: Workspace) => void;
}) {
  const [name, setName] = useState(workspace.name);
  const [rootPath, setRootPath] = useState(workspace.root_path);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const save = async () => {
    setSaving(true);
    setError("");
    try {
      onSaved(
        await json<Workspace>(`/api/workspaces/${workspace.id}`, {
          method: "PATCH",
          body: JSON.stringify({
            name: name.trim() || workspace.name,
            root_path: rootPath.trim(),
            description: workspace.description || "",
          }),
        }),
      );
    } catch (e) {
      setError(String(e));
      setSaving(false);
    }
  };
  return (
    <div className="modal-backdrop">
      <div className="modal">
        <div className="modal-head">
          <h2>编辑工作空间</h2>
          <button onClick={onClose}>×</button>
        </div>
        <label>
          名称
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label>
          本机文件夹完整路径
          <input
            value={rootPath}
            onChange={(event) => setRootPath(event.target.value)}
          />
        </label>
        <p className="modal-note">
          修改路径后，后续任务会使用新路径；已有任务仍保留在当前空间下。
        </p>
        {error && <p className="modal-error">{error}</p>}
        <div className="modal-actions">
          <button className="secondary-button" onClick={onClose}>
            取消
          </button>
          <button
            className="primary-button"
            disabled={!rootPath.trim() || saving}
            onClick={save}
          >
            {saving ? "保存中…" : "保存修改"}
          </button>
        </div>
      </div>
    </div>
  );
}
