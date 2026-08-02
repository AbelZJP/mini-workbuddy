import React, { useState } from "react";
import type { ToolLog } from "../../app/types";

export function formatToolValue(value: unknown): string {
  if (value === undefined || value === null || value === "") return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function ToolLogs({ logs }: { logs?: ToolLog[] }) {
  const [open, setOpen] = useState(false);
  const visibleLogs = (logs || []).filter(
    (log) => !(log.kind === "skill" && log.status === "loaded"),
  );
  if (!visibleLogs.length) return null;
  const statusLabel = (status?: string) =>
    status === "completed"
      ? "已完成"
      : status === "failed"
        ? "失败"
        : status === "loaded"
          ? "已加载"
          : status === "waiting_approval"
            ? "等待授权"
            : "执行中";
  return (
    <div className="tool-logs">
      <button
        className="tool-logs-toggle"
        type="button"
        onClick={() => setOpen((current) => !current)}
      >
        <span className="tool-logs-mark">⌁</span>
        <span>调用日志</span>
        <b>{visibleLogs.length}</b>
        <span className="tool-logs-chevron">{open ? "⌃" : "⌄"}</span>
      </button>
      {open && (
        <div className="tool-log-list">
          {visibleLogs.map((log, index) => (
            <details
              className="tool-log-item"
              key={`${log.id}-${index}`}
              open={
                index === visibleLogs.length - 1 && log.status === "running"
              }
            >
              <summary>
                <span className={`tool-kind ${log.kind || "tool"}`}>
                  {log.kind === "mcp"
                    ? "MCP"
                    : log.kind === "skill"
                      ? "Skill"
                      : log.kind === "expert"
                        ? "专家"
                      : "工具"}
                </span>
                <strong>{log.name}</strong>
                <span className={`tool-status ${log.status || "running"}`}>
                  {statusLabel(log.status)}
                </span>
              </summary>
              <div className="tool-log-detail">
                {formatToolValue(log.input) && (
                  <div>
                    <small>输入</small>
                    <pre>{formatToolValue(log.input)}</pre>
                  </div>
                )}
                {formatToolValue(log.output) && (
                  <div>
                    <small>输出</small>
                    <pre>{formatToolValue(log.output)}</pre>
                  </div>
                )}
                {log.artifact_path && (
                  <div>
                    <small>已生成产物</small>
                    <pre>{log.artifact_path}</pre>
                  </div>
                )}
              </div>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}
