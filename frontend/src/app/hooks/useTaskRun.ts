import React, { useRef, useState } from "react";
import { api, json, taskTitleFromMessage } from "../api";
import type {
  Approval,
  ApprovalCall,
  Attachment,
  Message,
  Run,
  Task,
  ToolLog,
} from "../types";

type TaskRunOptions = {
  input: string;
  attachments: Attachment[];
  uploading: boolean;
  taskId: string;
  task?: Task;
  workspaceId: string;
  permission: string;
  modelId: string;
  setInput: (value: string) => void;
  setAttachments: React.Dispatch<React.SetStateAction<Attachment[]>>;
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>;
  setTasksByWorkspace: React.Dispatch<
    React.SetStateAction<Record<string, Task[]>>
  >;
  setError: (value: string) => void;
};

export function useTaskRun(options: TaskRunOptions) {
  const {
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
  } = options;
  const [running, setRunning] = useState(false);
  const requestRef = useRef<AbortController | null>(null);
  const runIdRef = useRef<string | null>(null);
  const runSequenceRef = useRef(0);

  const send = async () => {
    if (
      (!input.trim() && !attachments.length) ||
      uploading ||
      running ||
      !taskId
    )
      return;
    const text = input.trim();
    const currentAttachments = attachments;
    const attachmentText = currentAttachments.length
      ? `\n\n附件（已复制到当前工作空间）：\n${currentAttachments.map((item) => `- ${item.path}`).join("\n")}`
      : "";
    const content = `${text || "请查看我附加的文件"}${attachmentText}`;
    setInput("");
    setAttachments([]);
    setRunning(true);
    setError("");
    setMessages((current) => [
      ...current,
      { role: "user", content },
      { role: "assistant", content: "" },
    ]);
    const controller = new AbortController();
    requestRef.current = controller;
    runIdRef.current = null;
    runSequenceRef.current = 0;
    let assistant = "";
    let terminal = false;
    const applyEvent = (event: {
      type?: string;
      run_id?: string;
      sequence?: number;
      content?: string;
      log?: ToolLog;
      name?: string;
      label?: string;
      approval_id?: string;
      message?: string;
      tool_calls?: ApprovalCall[];
    }) => {
      if (event.run_id) runIdRef.current = event.run_id;
      if (event.sequence)
        runSequenceRef.current = Math.max(
          runSequenceRef.current,
          event.sequence,
        );
      if (event.type === "assistant.delta") {
        assistant += event.content || "";
        setMessages((current) =>
          current.map((item, index) =>
            index === current.length - 1
              ? { ...item, content: assistant }
              : item,
          ),
        );
      }
      if (
        event.type === "tool.started" ||
        event.type === "tool.updated" ||
        event.type === "tool.completed"
      ) {
        const incoming = event.log || {
          id: event.name || `log-${Date.now()}`,
          name: event.name || "工具调用",
          kind: "tool",
          status: "completed",
          output: event.label || "",
        };
        setMessages((current) =>
          current.map((item, index) => {
            if (index !== current.length - 1) return item;
            const logs = item.metadata?.tool_logs || [];
            const found = logs.findIndex((log) => log.id === incoming.id);
            const nextLogs =
              found >= 0
                ? logs.map((log, logIndex) =>
                    logIndex === found ? { ...log, ...incoming } : log,
                  )
                : [...logs, incoming];
            return {
              ...item,
              metadata: { ...item.metadata, tool_logs: nextLogs },
            };
          }),
        );
      }
      if (event.type === "tool.approval_required" && event.approval_id) {
        const approval: Approval = {
          id: event.approval_id,
          message: event.message,
          tool_calls: event.tool_calls || [],
          status: "pending",
        };
        setMessages((current) =>
          current.map((item, index) => {
            if (index !== current.length - 1) return item;
            const approvals = item.metadata?.approvals || [];
            const found = approvals.findIndex(
              (entry) => entry.id === approval.id,
            );
            const nextApprovals =
              found >= 0
                ? approvals.map((entry, approvalIndex) =>
                    approvalIndex === found ? { ...entry, ...approval } : entry,
                  )
                : [...approvals, approval];
            return {
              ...item,
              metadata: { ...item.metadata, approvals: nextApprovals },
            };
          }),
        );
      }
      if (event.type === "tool.external_required") {
        setMessages((current) =>
          current.map((item, index) =>
            index === current.length - 1
              ? {
                  ...item,
                  content: `${item.content || ""}\n\n${event.message || "该工具需要外部执行器，当前没有可用的执行器。"}`,
                }
              : item,
          ),
        );
      }
      if (event.type === "task.completed") {
        terminal = true;
        setTasksByWorkspace((current) => ({
          ...current,
          [workspaceId]: (current[workspaceId] || []).map((item) =>
            item.id === taskId
              ? { ...item, status: "completed", current_state: "已完成" }
              : item,
          ),
        }));
      }
      if (event.type === "task.failed" || event.type === "task.cancelled")
        terminal = true;
    };
    const readStream = async (response: Response) => {
      const reader = response.body?.getReader();
      if (!reader) throw new Error("流式响应不可用");
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() || "";
        chunks.forEach((chunk) => {
          const line = chunk
            .split("\n")
            .find((item) => item.startsWith("data: "));
          if (!line) return;
          applyEvent(JSON.parse(line.slice(6)));
        });
      }
      if (buffer.trim()) {
        const line = buffer
          .split("\n")
          .find((item) => item.startsWith("data: "));
        if (line) applyEvent(JSON.parse(line.slice(6)));
      }
    };
    const refreshTerminalState = async () => {
      if (!runIdRef.current) return;
      const run = await json<Run>(`/api/runs/${runIdRef.current}`);
      if (["completed", "failed", "cancelled"].includes(run.status))
        terminal = true;
    };
    const reconnect = async () => {
      let lastError: unknown = null;
      for (let attempt = 0; attempt < 5 && !terminal; attempt += 1) {
        try {
          if (!runIdRef.current) {
            const latest = await json<Run | null>(
              `/api/tasks/${taskId}/runs/latest`,
            );
            if (latest) runIdRef.current = latest.id;
          }
          if (!runIdRef.current) throw new Error("未找到后台 Run，无法重连");
          await new Promise((resolve) =>
            window.setTimeout(resolve, Math.min(1000 * (attempt + 1), 4000)),
          );
          const response = await api(
            `/api/runs/${runIdRef.current}/events?after=${runSequenceRef.current}`,
            { signal: controller.signal },
          );
          await readStream(response);
          await refreshTerminalState();
          if (!terminal) throw new Error("SSE 连接提前断开");
        } catch (e) {
          if ((e as Error).name === "AbortError") throw e;
          lastError = e;
        }
      }
      if (!terminal)
        throw lastError || new Error("SSE 重连失败，请稍后查看 Run 状态");
    };
    try {
      const response = await api(`/api/tasks/${taskId}/messages`, {
        method: "POST",
        signal: controller.signal,
        body: JSON.stringify({
          content,
          workspace_id: workspaceId,
          permission_mode: permission,
          model_id: modelId,
          attachments: currentAttachments,
        }),
      });
      if (task?.title === "新任务")
        setTasksByWorkspace((current) => ({
          ...current,
          [workspaceId]: (current[workspaceId] || []).map((item) =>
            item.id === taskId
              ? { ...item, title: taskTitleFromMessage(text) }
              : item,
          ),
        }));
      await readStream(response);
      if (!terminal) {
        await refreshTerminalState();
        if (!terminal) throw new Error("SSE 连接提前断开，正在尝试重连");
      }
    } catch (e) {
      if ((e as Error).name === "AbortError") {
        setMessages((current) => current.slice(0, -1));
      } else {
        try {
          setError("连接已断开，正在重连后台 Run…");
          await reconnect();
          setError("");
        } catch (reconnectError) {
          if ((reconnectError as Error).name !== "AbortError") {
            setError(
              `执行连接失败：${String(reconnectError).replace(/^Error:\s*/, "")}`,
            );
            setMessages((current) => current.slice(0, -1));
          }
        }
      }
    } finally {
      requestRef.current = null;
      runIdRef.current = null;
      runSequenceRef.current = 0;
      setRunning(false);
    }
  };
  const cancel = async () => {
    const runId = runIdRef.current;
    requestRef.current?.abort();
    try {
      if (runId) await api(`/api/runs/${runId}/cancel`, { method: "POST" });
      else if (taskId)
        await api(`/api/tasks/${taskId}/cancel`, { method: "POST" });
    } catch (e) {
      setError(String(e));
    }
    setRunning(false);
  };

  return { running, send, cancel };
}
