import { useMemo, useState } from "react";
import { api, json } from "./api";
import type { Attachment, Message, Model, Task, Workspace } from "./types";
import { Chat } from "../features/chat/Chat";
import { SkillsPage } from "../features/skills/SkillsPage";
import { ExpertsPage } from "../features/experts/ExpertsPage";
import { McpPage } from "../features/mcp/McpPage";
import { SettingsPage } from "../features/settings/SettingsPage";
import {
  CreateWorkspaceModal,
  WorkspaceModal,
} from "../features/workspaces/WorkspaceModals";
import { useAppBootstrap } from "./hooks/useAppBootstrap";
import { useCapabilities } from "./hooks/useCapabilities";
import { useTaskRun } from "./hooks/useTaskRun";
import { useWorkspaceTasks } from "./hooks/useWorkspaceTasks";

export function App() {
  const [section, setSection] = useState<
    "chat" | "skills" | "experts" | "mcp" | "settings"
  >("chat");
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState("default");
  const [tasksByWorkspace, setTasksByWorkspace] = useState<
    Record<string, Task[]>
  >({});
  const [taskId, setTaskId] = useState("welcome");
  const [messages, setMessages] = useState<Message[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [modelId, setModelId] = useState("demo");
  const [permission, setPermission] = useState("workspace");
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [editingWorkspace, setEditingWorkspace] = useState<Workspace | null>(
    null,
  );
  const [collapsedWorkspaces, setCollapsedWorkspaces] = useState<
    Record<string, boolean>
  >({});
  const workspace = useMemo(
    () => workspaces.find((item) => item.id === workspaceId),
    [workspaces, workspaceId],
  );
  const tasks = tasksByWorkspace[workspaceId] || [];
  const task = useMemo(
    () => tasks.find((item) => item.id === taskId),
    [tasks, taskId],
  );

  const { refresh } = useAppBootstrap({
    workspaceId,
    setWorkspaceId,
    setWorkspaces,
    setTasksByWorkspace,
    setModels,
    setModelId,
    setError,
  });
  const { selectWorkspace, uploadFiles } = useWorkspaceTasks({
    workspaceId,
    taskId,
    tasksByWorkspace,
    setWorkspaceId,
    setTaskId,
    setTasksByWorkspace,
    setUploading,
    setAttachments,
    setMessages,
    setSection,
    setError,
  });
  const { updateTaskCapabilities } = useCapabilities({
    taskId,
    workspaceId,
    setTasksByWorkspace,
    setError,
  });
  const { running, send, cancel } = useTaskRun({
    input,
    attachments,
    uploading,
    taskId,
    task,
    workspaceId,
    permission,
    modelId,
    setInput,
    setAttachments,
    setMessages,
    setTasksByWorkspace,
    setError,
  });

  const createTask = async (targetWorkspaceId = workspaceId) => {
    try {
      const created = await json<Task>("/api/tasks", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: targetWorkspaceId,
          title: "新任务",
          permission_mode: permission,
          model_id: modelId,
        }),
      });
      setTasksByWorkspace((current) => ({
        ...current,
        [targetWorkspaceId]: [created, ...(current[targetWorkspaceId] || [])],
      }));
      setWorkspaceId(targetWorkspaceId);
      setTaskId(created.id);
      setMessages([]);
      setAttachments([]);
      setSection("chat");
    } catch (e) {
      setError(String(e));
    }
  };
  const deleteWorkspace = async (item: Workspace) => {
    if (
      item.id === "default" ||
      !window.confirm(
        `删除工作空间“${item.name}”？其中的任务和消息也会被删除。`,
      )
    )
      return;
    try {
      await api(`/api/workspaces/${item.id}`, { method: "DELETE" });
      const remaining = workspaces.filter(
        (workspaceItem) => workspaceItem.id !== item.id,
      );
      setWorkspaces(remaining);
      setTasksByWorkspace((current) => {
        const next = { ...current };
        delete next[item.id];
        return next;
      });
      if (workspaceId === item.id) {
        const nextWorkspace = remaining[0];
        setWorkspaceId(nextWorkspace?.id || "");
        setTaskId("");
        setMessages([]);
      }
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">✦</div>
          <div>
            <strong>mini-workbuddy</strong>
            <span>personal workbench</span>
          </div>
        </div>
        <button className="new-task" onClick={() => createTask()}>
          <span>＋</span> 新建任务 <kbd>⌘ K</kbd>
        </button>
        <nav className="primary-nav">
          <button
            className={section === "skills" ? "active" : ""}
            onClick={() => setSection("skills")}
          >
            <span className="nav-icon">◈</span>技能 Skills
          </button>
          <button
            className={section === "mcp" ? "active" : ""}
            onClick={() => setSection("mcp")}
          >
            <span className="nav-icon">⌁</span>连接器 MCP
          </button>
          <button
            className={section === "experts" ? "active" : ""}
            onClick={() => setSection("experts")}
          >
            <span className="nav-icon">◎</span>专家库
          </button>
        </nav>
        <div className="workspace-label">
          <span>工作空间</span>
          <button onClick={() => setShowCreate(true)}>＋</button>
        </div>
        <div className="workspace-list">
          {workspaces.map((item) => {
            const collapsed = Boolean(collapsedWorkspaces[item.id]);
            const itemTasks = tasksByWorkspace[item.id] || [];
            return (
              <div key={item.id} className="workspace-group">
                <div className="workspace-row">
                  <button
                    className={`workspace-name ${item.id === workspaceId ? "selected" : ""}`}
                    title={`${collapsed ? "展开" : "收起"} ${item.name} 的对话`}
                    onClick={() => {
                      void selectWorkspace(item.id);
                      setCollapsedWorkspaces((current) => ({
                        ...current,
                        [item.id]: !collapsed,
                      }));
                    }}
                  >
                    <span className="workspace-chevron">
                      {collapsed ? "›" : "⌄"}
                    </span>
                    <span className="folder">▰</span>
                    {item.name}
                  </button>
                  <div className="workspace-actions">
                    <button
                      title="在此空间新建对话"
                      onClick={() => createTask(item.id)}
                    >
                      ＋
                    </button>
                    <button
                      title="编辑工作空间"
                      onClick={() => setEditingWorkspace(item)}
                    >
                      ✎
                    </button>
                    {item.id !== "default" && (
                      <button
                        title="删除工作空间"
                        onClick={() => deleteWorkspace(item)}
                      >
                        ×
                      </button>
                    )}
                  </div>
                </div>
                {!collapsed &&
                  itemTasks.map((taskItem) => (
                    <button
                      key={taskItem.id}
                      className={`task-item ${taskItem.id === taskId ? "selected" : ""}`}
                      onClick={() => {
                        setWorkspaceId(item.id);
                        setTaskId(taskItem.id);
                        setSection("chat");
                      }}
                    >
                      <span className="task-dot">·</span>
                      <span>{taskItem.title}</span>
                      <small>
                        {taskItem.status === "completed"
                          ? "完成"
                          : taskItem.status}
                      </small>
                    </button>
                  ))}
              </div>
            );
          })}
        </div>
        <div className="sidebar-footer">
          <button
            onClick={() => setSection("settings")}
            className={section === "settings" ? "active" : ""}
          >
            <span>⚙</span>设置
          </button>
          <div className="profile">
            <div className="avatar">W</div>
            <div>
              <b>本地用户</b>
              <span>Local workspace</span>
            </div>
            <span className="more">•••</span>
          </div>
        </div>
      </aside>
      <main className="main-panel">
        {error && (
          <div className="error-banner">
            {error}
            <button onClick={() => setError("")}>×</button>
          </div>
        )}
        {section === "chat" && (
          <Chat
            workspace={workspace}
            task={task}
            messages={messages}
            input={input}
            setInput={setInput}
            attachments={attachments}
            setAttachments={setAttachments}
            uploadFiles={uploadFiles}
            uploading={uploading}
            send={send}
            cancel={cancel}
            running={running}
            workspaceId={workspaceId}
            setWorkspaceId={selectWorkspace}
            workspaces={workspaces}
            permission={permission}
            setPermission={setPermission}
            modelId={modelId}
            setModelId={setModelId}
            models={models}
            updateCapabilities={updateTaskCapabilities}
          />
        )}
        {section === "skills" && <SkillsPage />}
        {section === "experts" && <ExpertsPage />}
        {section === "mcp" && <McpPage />}
        {section === "settings" && (
          <SettingsPage models={models} refresh={refresh} />
        )}
      </main>
      {showCreate && (
        <CreateWorkspaceModal
          onClose={() => setShowCreate(false)}
          onCreated={(item) => {
            setWorkspaces((current) => [...current, item]);
            setTasksByWorkspace((current) => ({ ...current, [item.id]: [] }));
            setWorkspaceId(item.id);
            setTaskId("");
            setMessages([]);
            setShowCreate(false);
          }}
        />
      )}
      {editingWorkspace && (
        <WorkspaceModal
          workspace={editingWorkspace}
          onClose={() => setEditingWorkspace(null)}
          onSaved={(item) => {
            setWorkspaces((current) =>
              current.map((entry) => (entry.id === item.id ? item : entry)),
            );
            setEditingWorkspace(null);
          }}
        />
      )}
    </div>
  );
}
