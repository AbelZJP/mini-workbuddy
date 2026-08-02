import { useState } from "react";
import { api } from "../../app/api";
import type { Approval } from "../../app/types";
import { formatToolValue } from "./ToolLogs";

export function ApprovalCard({
  taskId,
  approval,
}: {
  taskId: string;
  approval: Approval;
}) {
  const [status, setStatus] = useState(approval.status || "pending");
  const [saving, setSaving] = useState(false);
  const resolve = async (approved: boolean) => {
    if (saving || status !== "pending") return;
    setSaving(true);
    try {
      await api(
        `/api/tasks/${taskId}/approvals/${encodeURIComponent(approval.id)}`,
        { method: "POST", body: JSON.stringify({ approved }) },
      );
      setStatus(approved ? "approved" : "rejected");
    } catch (error) {
      window.alert(`授权处理失败：${String(error)}`);
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className={`approval-card ${status}`}>
      <div className="approval-head">
        <span className="approval-icon">!</span>
        <div>
          <strong>
            {status === "pending"
              ? "需要你的确认"
              : status === "approved"
                ? "已允许执行"
                : "已拒绝执行"}
          </strong>
          <small>{approval.message || "该工具调用需要确认后才能继续。"}</small>
        </div>
      </div>
      {approval.tool_calls.map((call) => (
        <div className="approval-call" key={call.id}>
          <b>{call.name}</b>
          {formatToolValue(call.input) && (
            <pre>{formatToolValue(call.input)}</pre>
          )}
        </div>
      ))}
      {status === "pending" && (
        <div className="approval-actions">
          <button
            className="secondary-button"
            disabled={saving}
            onClick={() => void resolve(false)}
          >
            拒绝
          </button>
          <button
            className="primary-button"
            disabled={saving}
            onClick={() => void resolve(true)}
          >
            {saving ? "处理中…" : "允许执行"}
          </button>
        </div>
      )}
    </div>
  );
}
