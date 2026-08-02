import React, { useEffect, useRef, useState } from "react";
import { api, json } from "../../app/api";
import type {
  ApprovalCall,
  Attachment,
  Message,
  Model,
  Task,
  Workspace,
} from "../../app/types";
import { ThemeSelect } from "../../components/common";
import { ApprovalCard } from "./ApprovalCard";
import { CapabilityPicker } from "./CapabilityPicker";
import { MarkdownContent } from "./MarkdownContent";
import { ToolLogs } from "./ToolLogs";

export function Chat({
  workspace,
  task,
  messages,
  input,
  setInput,
  attachments,
  setAttachments,
  uploadFiles,
  uploading,
  send,
  cancel,
  running,
  workspaceId,
  setWorkspaceId,
  workspaces,
  permission,
  setPermission,
  modelId,
  setModelId,
  models,
  updateCapabilities,
}: {
  workspace?: Workspace;
  task?: Task;
  messages: Message[];
  input: string;
  setInput: (value: string) => void;
  attachments: Attachment[];
  setAttachments: React.Dispatch<React.SetStateAction<Attachment[]>>;
  uploadFiles: (files: File[]) => Promise<void>;
  uploading: boolean;
  send: () => void;
  cancel: () => void;
  running: boolean;
  workspaceId: string;
  setWorkspaceId: (value: string) => void;
  workspaces: Workspace[];
  permission: string;
  setPermission: (value: string) => void;
  modelId: string;
  setModelId: (value: string) => void;
  models: Model[];
  updateCapabilities: (
    skillIds: string[],
    expertIds: string[],
  ) => Promise<void>;
}) {
  const conversationRef = useRef<HTMLElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const followOutputRef = useRef(true);
  const scrollFrameRef = useRef<number | null>(null);

  const scrollToBottom = () => {
    if (scrollFrameRef.current !== null) return;
    scrollFrameRef.current = requestAnimationFrame(() => {
      scrollFrameRef.current = null;
      if (!followOutputRef.current) return;
      const conversation = conversationRef.current;
      if (conversation) conversation.scrollTop = conversation.scrollHeight;
    });
  };

  useEffect(() => {
    followOutputRef.current = true;
    scrollToBottom();
  }, [task?.id]);

  useEffect(() => {
    if (followOutputRef.current) scrollToBottom();
  }, [messages]);

  const handleSend = () => {
    followOutputRef.current = true;
    send();
    scrollToBottom();
  };

  return (
    <>
      <header className="topbar">
        <div>
          <span className="eyebrow">
            WORKSPACE / {workspace?.name || "默认工作空间"}
          </span>
          <h1>{task?.title || "新任务"}</h1>
        </div>
        <div className="top-actions">
          <span className="status-pill">
            <i />
            本地运行中
          </span>
          <button
            className="icon-button"
            title="刷新页面"
            onClick={() => window.location.reload()}
          >
            ↻
          </button>
          <button
            className="icon-button"
            title="压缩当前上下文"
            onClick={() =>
              task && fetch(`/api/tasks/${task.id}/compact`, { method: "POST" })
            }
          >
            ⋯
          </button>
        </div>
      </header>
      <section
        className="conversation"
        ref={conversationRef}
        onScroll={(event) => {
          const element = event.currentTarget;
          const atBottom =
            element.scrollHeight - element.scrollTop - element.clientHeight <
            72;
          followOutputRef.current = atBottom;
        }}
        onWheel={(event) => {
          if (event.deltaY < 0) followOutputRef.current = false;
        }}
      >
        <div className="conversation-inner">
          {messages.length === 0 && (
            <div className="empty-state">
              <div className="empty-orb">✦</div>
              <h2>今天想一起完成什么？</h2>
              <p>
                选择一个工作空间，描述你的任务，mini-workbuddy
                会帮你规划并执行。
              </p>
              <div className="suggestions">
                <button
                  onClick={() =>
                    setInput("整理工作空间里的文件，并生成一份摘要")
                  }
                >
                  整理我的文件
                </button>
                <button onClick={() => setInput("根据当前资料写一份周报")}>
                  写一份周报
                </button>
                <button onClick={() => setInput("分析工作空间里的数据文件")}>
                  分析数据
                </button>
              </div>
            </div>
          )}
          {messages.map((message, index) => (
            <div key={index} className={`message-row ${message.role}`}>
              <div className="message-avatar">
                {message.role === "assistant" ? "✦" : "W"}
              </div>
              <div className="message-body">
                <div className="message-meta">
                  {message.role === "assistant" ? "mini-workbuddy" : "你"}
                  <span>
                    {index === messages.length - 1 && running
                      ? "正在工作…"
                      : "刚刚"}
                  </span>
                </div>
                <div className="message-content">
                  {message.content ? (
                    message.role === "assistant" ? (
                      <MarkdownContent content={message.content} />
                    ) : (
                      message.content
                    )
                  ) : (
                    <span className="typing">
                      <i />
                      <i />
                      <i />
                    </span>
                  )}
                </div>
                {message.role === "assistant" && (
                  <>
                    <ToolLogs logs={message.metadata?.tool_logs} />
                    {message.metadata?.approvals?.map((approval) => (
                      <ApprovalCard
                        key={approval.id}
                        taskId={task?.id || ""}
                        approval={approval}
                      />
                    ))}
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>
      <div className="composer-wrap">
        <div className="composer">
          {attachments.length > 0 && (
            <div className="attachment-list">
              {attachments.map((item, index) => (
                <div className="attachment-chip" key={item.path + index}>
                  <span>📎 {item.name}</span>
                  <button
                    type="button"
                    title="移除附件"
                    onClick={() =>
                      setAttachments((current) =>
                        current.filter((_, itemIndex) => itemIndex !== index),
                      )
                    }
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onPaste={(event) => {
              const files = Array.from(event.clipboardData.files);
              if (files.length) {
                event.preventDefault();
                void uploadFiles(files);
              }
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                handleSend();
              }
            }}
            placeholder="描述你想完成的任务，或直接粘贴文件…"
          />
          <input
            ref={fileInputRef}
            type="file"
            multiple
            hidden
            onChange={(event) => {
              const files = Array.from(event.target.files || []);
              if (files.length) void uploadFiles(files);
              event.currentTarget.value = "";
            }}
          />
          <div className="composer-toolbar">
            <div className="toolbar-left">
              <CapabilityPicker
                task={task}
                fileInputRef={fileInputRef}
                uploading={uploading}
                updateCapabilities={updateCapabilities}
              />
              <ThemeSelect
                label="工作空间"
                value={workspaceId}
                onChange={setWorkspaceId}
                options={workspaces.map((item) => ({
                  value: item.id,
                  label: item.name,
                }))}
              />
              <ThemeSelect
                label="权限"
                value={permission}
                onChange={setPermission}
                options={[
                  { value: "readonly", label: "只读" },
                  { value: "workspace", label: "可修改工作区" },
                  { value: "command", label: "允许执行命令" },
                  { value: "autonomous", label: "完全自主" },
                ]}
              />
            </div>
            <div className="toolbar-right">
              <ThemeSelect
                label="模型"
                value={modelId}
                onChange={setModelId}
                options={models.map((item) => ({
                  value: item.id,
                  label: item.name,
                }))}
              />
              <button
                className={`send-button ${running ? "stop" : ""}`}
                onClick={running ? cancel : handleSend}
              >
                {running ? "■" : "↑"}
              </button>
            </div>
          </div>
        </div>
        <p className="composer-hint">
          支持上传文件，也可添加任务级技能、专家和连接器。
        </p>
      </div>
    </>
  );
}

type CapabilityPanel = "root" | "skills" | "experts" | "mcp" | null;
