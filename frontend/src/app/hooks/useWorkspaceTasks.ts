import { useEffect } from "react";
import { json } from "../api";
import type { Attachment, Message, Task } from "../types";

type WorkspaceTasksOptions = {
  workspaceId: string;
  taskId: string;
  tasksByWorkspace: Record<string, Task[]>;
  setWorkspaceId: (value: string) => void;
  setTaskId: (value: string) => void;
  setTasksByWorkspace: React.Dispatch<
    React.SetStateAction<Record<string, Task[]>>
  >;
  setUploading: (value: boolean) => void;
  setAttachments: React.Dispatch<React.SetStateAction<Attachment[]>>;
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>;
  setSection: (
    value: "chat" | "skills" | "experts" | "canvas" | "mcp" | "settings",
  ) => void;
  setError: (value: string) => void;
};

export function useWorkspaceTasks(options: WorkspaceTasksOptions) {
  const {
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
  } = options;

  const loadWorkspaceTasks = (id: string) =>
    json<Task[]>(`/api/workspaces/${id}/tasks`).then((data) => {
      setTasksByWorkspace((current) => ({ ...current, [id]: data }));
      return data;
    });

  const selectWorkspace = async (id: string) => {
    setWorkspaceId(id);
    setAttachments([]);
    setSection("chat");
    try {
      const data = tasksByWorkspace[id] || (await loadWorkspaceTasks(id));
      const nextTask = data[0];
      setTaskId(nextTask?.id || "");
      if (!nextTask) setMessages([]);
    } catch (error) {
      setError(String(error));
    }
  };

  const uploadFiles = async (files: File[]) => {
    if (!files.length || !workspaceId) return;
    setUploading(true);
    setError("");
    try {
      const form = new FormData();
      files.forEach((file) => {
        const relativePath =
          (file as File & { webkitRelativePath?: string }).webkitRelativePath ||
          file.name;
        form.append("files", file, relativePath);
      });
      const response = await fetch(`/api/workspaces/${workspaceId}/files`, {
        method: "POST",
        body: form,
      });
      if (!response.ok) throw new Error(await response.text());
      const data = (await response.json()) as { files: Attachment[] };
      setAttachments((current) => [...current, ...data.files]);
    } catch (error) {
      setError(`文件上传失败：${String(error)}`);
    } finally {
      setUploading(false);
    }
  };

  useEffect(() => {
    if (!workspaceId) return;
    loadWorkspaceTasks(workspaceId)
      .then((data) => {
        const nextTask = data.find((item) => item.id === taskId) || data[0];
        setTaskId(nextTask?.id || "");
        if (!nextTask) setMessages([]);
      })
      .catch((error) => setError(String(error)));
  }, [workspaceId]);

  useEffect(() => {
    if (taskId) {
      json<Message[]>(`/api/tasks/${taskId}/messages`)
        .then(setMessages)
        .catch((error) => setError(String(error)));
    }
  }, [taskId]);

  return { loadWorkspaceTasks, selectWorkspace, uploadFiles };
}
