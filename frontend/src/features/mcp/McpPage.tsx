import React, { useEffect, useState } from "react";
import { api, json } from "../../app/api";
import type { Mcp } from "../../app/types";
import { EmptyCard, ManagementShell } from "../../components/common";
import { McpModal } from "./McpModal";

export function McpPage() {
  const [items, setItems] = useState<Mcp[]>([]);
  const [show, setShow] = useState(false);
  const [result, setResult] = useState("");
  const load = () => json<Mcp[]>("/api/mcp").then(setItems);
  useEffect(() => {
    load();
  }, []);
  const test = async (id: string) => {
    try {
      const data = await json<{
        ok: boolean;
        count?: number;
        tools?: string[];
        error?: string;
      }>(`/api/mcp/${encodeURIComponent(id)}/test`, { method: "POST" });
      setResult(
        data.ok
          ? `连接成功：发现 ${data.count} 个工具\n${data.tools?.join(", ") || ""}`
          : `连接失败：${data.error}`,
      );
    } catch (e) {
      setResult(`连接失败：${String(e).replace(/^Error:\s*/, "")}`);
    }
  };
  const remove = async (item: Mcp) => {
    if (!window.confirm(`确定删除 MCP 连接器“${item.name}”？`)) return;
    try {
      await api(`/api/mcp/${encodeURIComponent(item.id)}`, {
        method: "DELETE",
      });
      setItems((current) => current.filter((entry) => entry.id !== item.id));
      setResult(`已删除连接器：${item.name}`);
    } catch (e) {
      setResult(`删除失败：${String(e).replace(/^Error:\s*/, "")}`);
    }
  };
  return (
    <ManagementShell
      eyebrow="CAPABILITIES"
      title="⌁ 连接器 MCP"
      subtitle="配置、测试并启用真实 MCP 服务和工具白名单"
      action="添加连接器"
      onAction={() => setShow(true)}
    >
      <div className="management-grid">
        {items.length === 0 && <EmptyCard text="尚未配置 MCP 连接器。" />}
        {items.map((item) => (
          <article className="capability-card" key={item.id}>
            <div className="card-icon">⌁</div>
            <div>
              <h3>{item.name}</h3>
              <p>
                {item.transport} · {item.url || item.command}
              </p>
            </div>
            <button
              className={`toggle ${item.enabled ? "on" : ""}`}
              onClick={() =>
                json(`/api/mcp/${encodeURIComponent(item.id)}`, {
                  method: "PATCH",
                  body: JSON.stringify({ enabled: !item.enabled }),
                }).then(load)
              }
            >
              <i />
            </button>
            <button className="small-button" onClick={() => void test(item.id)}>
              测试
            </button>
            <button
              className="small-button danger-small-button"
              onClick={() => void remove(item)}
            >
              删除
            </button>
          </article>
        ))}
      </div>
      {result && <div className="result-box">{result}</div>}
      {show && (
        <McpModal
          onClose={() => setShow(false)}
          onCreated={() => {
            setShow(false);
            load();
          }}
        />
      )}
    </ManagementShell>
  );
}
