import React, { useEffect, useRef, useState } from "react";
import { json } from "../../app/api";
import type { Expert, ExpertResponse, Mcp, Skill, Task } from "../../app/types";

type CapabilityPanel = "root" | "skills" | "experts" | "mcp" | null;

export function CapabilityPicker({
  task,
  fileInputRef,
  uploading,
  updateCapabilities,
}: {
  task?: Task;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  uploading: boolean;
  updateCapabilities: (
    skillIds: string[],
    expertIds: string[],
  ) => Promise<void>;
}) {
  const [panel, setPanel] = useState<CapabilityPanel>(null);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [experts, setExperts] = useState<Expert[]>([]);
  const [mcps, setMcps] = useState<Mcp[]>([]);
  const [saving, setSaving] = useState("");
  const [error, setError] = useState("");
  const pickerRef = useRef<HTMLDivElement | null>(null);
  const selectedSkills = task?.selected_skill_ids || [];
  const selectedExperts = task?.selected_expert_ids || [];
  const capabilityWorkspaceId = task?.workspace_id || "default";

  const loadOptions = async () => {
    try {
      const [localSkills, expertData, connectors] = await Promise.all([
        json<Skill[]>(
          `/api/skills?workspace_id=${encodeURIComponent(capabilityWorkspaceId)}`,
        ),
        json<ExpertResponse>("/api/experts?installed=true"),
        json<Mcp[]>("/api/mcp"),
      ]);
      setSkills(localSkills.filter((item) => item.enabled));
      setExperts(expertData.items);
      setMcps(connectors);
      setError("");
    } catch (reason) {
      setError(
        `读取已安装能力失败：${String(reason).replace(/^Error:\s*/, "")}`,
      );
    }
  };
  useEffect(() => {
    void loadOptions();
  }, [task?.id, capabilityWorkspaceId]);
  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (
        pickerRef.current &&
        !pickerRef.current.contains(event.target as Node)
      )
        setPanel(null);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const open = () => {
    setPanel((current) => (current ? null : "root"));
    void loadOptions();
  };
  const toggleCapability = async (kind: "skill" | "expert", id: string) => {
    if (!task) return;
    const source = kind === "skill" ? selectedSkills : selectedExperts;
    const next = source.includes(id)
      ? source.filter((item) => item !== id)
      : [...source, id];
    setSaving(`${kind}:${id}`);
    await updateCapabilities(
      kind === "skill" ? next : selectedSkills,
      kind === "expert" ? next : selectedExperts,
    );
    setSaving("");
  };
  const toggleMcp = async (connector: Mcp) => {
    setSaving(`mcp:${connector.id}`);
    setError("");
    try {
      const updated = await json<Mcp>(
        `/api/mcp/${encodeURIComponent(connector.id)}`,
        {
          method: "PATCH",
          body: JSON.stringify({ enabled: !connector.enabled }),
        },
      );
      setMcps((current) =>
        current.map((item) =>
          item.id === updated.id ? { ...item, ...updated } : item,
        ),
      );
    } catch (reason) {
      setError(`更新连接器失败：${String(reason).replace(/^Error:\s*/, "")}`);
    } finally {
      setSaving("");
    }
  };
  const chip = (kind: "skill" | "expert", id: string) => {
    const item =
      kind === "skill"
        ? skills.find((entry) => entry.id === id)
        : experts.find((entry) => entry.id === id);
    const name = item?.name || id;
    return (
      <span className={`capability-chip ${kind}`} key={`${kind}-${id}`}>
        <i>{kind === "skill" ? "◆" : "◎"}</i>
        <span className="capability-chip-name" title={name}>
          {name}
        </span>
        <button
          type="button"
          title={`移除${name}`}
          disabled={saving === `${kind}:${id}`}
          onClick={() => void toggleCapability(kind, id)}
        >
          ×
        </button>
      </span>
    );
  };
  const selected = (
    <>
      {selectedSkills.map((id) => chip("skill", id))}
      {selectedExperts.map((id) => chip("expert", id))}
    </>
  );
  return (
    <div className="capability-picker" ref={pickerRef}>
      <button
        type="button"
        className={`round-tool ${panel ? "active" : ""}`}
        title="添加文件、技能、专家或连接器"
        disabled={uploading}
        onClick={open}
      >
        {uploading ? "…" : "＋"}
      </button>
      {selected}
      {panel && (
        <div className="capability-menu" role="menu">
          {panel === "root" && (
            <>
              <button
                type="button"
                className="capability-menu-item"
                onClick={() => {
                  fileInputRef.current?.click();
                  setPanel(null);
                }}
              >
                <span className="capability-menu-icon">⌁</span>
                <span>
                  <b>添加文件</b>
                  <small>上传文件或粘贴文件</small>
                </span>
              </button>
              <button
                type="button"
                className="capability-menu-item"
                onClick={() => setPanel("skills")}
              >
                <span className="capability-menu-icon">◆</span>
                <span>
                  <b>技能</b>
                  <small>选择已安装的 Skill</small>
                </span>
                <i>›</i>
              </button>
              <button
                type="button"
                className="capability-menu-item"
                onClick={() => setPanel("experts")}
              >
                <span className="capability-menu-icon">◎</span>
                <span>
                  <b>专家</b>
                  <small>作为任务级提示词注入</small>
                </span>
                <i>›</i>
              </button>
              <button
                type="button"
                className="capability-menu-item"
                onClick={() => setPanel("mcp")}
              >
                <span className="capability-menu-icon">⌁</span>
                <span>
                  <b>连接器</b>
                  <small>直接开关已配置 MCP</small>
                </span>
                <i>›</i>
              </button>
            </>
          )}
          {panel !== "root" && (
            <>
              <div className="capability-menu-head">
                <button type="button" onClick={() => setPanel("root")}>
                  ‹ 返回
                </button>
                <strong>
                  {panel === "skills"
                    ? "已安装技能"
                    : panel === "experts"
                      ? "已安装专家"
                      : "连接器 MCP"}
                </strong>
              </div>
              {panel === "skills" &&
                (skills.length ? (
                  skills.map((item) => (
                    <button
                      type="button"
                      className={`capability-choice ${selectedSkills.includes(item.id) ? "selected" : ""}`}
                      key={item.id}
                      disabled={saving === `skill:${item.id}`}
                      onClick={() => void toggleCapability("skill", item.id)}
                    >
                      <span>
                        <b>{item.name}</b>
                        <small>{item.description || item.id}</small>
                      </span>
                      <i>{selectedSkills.includes(item.id) ? "✓" : "+"}</i>
                    </button>
                  ))
                ) : (
                  <p className="capability-empty">
                    没有可选技能，请先在技能页安装并启用。
                  </p>
                ))}
              {panel === "experts" &&
                (experts.length ? (
                  experts.map((item) => (
                    <button
                      type="button"
                      className={`capability-choice ${selectedExperts.includes(item.id) ? "selected" : ""}`}
                      key={item.id}
                      disabled={saving === `expert:${item.id}`}
                      onClick={() => void toggleCapability("expert", item.id)}
                    >
                      <span>
                        <b>{item.name}</b>
                        <small>
                          {item.department} · {item.description || item.id}
                        </small>
                      </span>
                      <i>{selectedExperts.includes(item.id) ? "✓" : "+"}</i>
                    </button>
                  ))
                ) : (
                  <p className="capability-empty">
                    没有已安装专家，请先在专家库安装。
                  </p>
                ))}
              {panel === "mcp" &&
                (mcps.length ? (
                  mcps.map((item) => (
                    <div className="capability-mcp" key={item.id}>
                      <span>
                        <b>{item.name}</b>
                        <small>
                          {item.transport} · {item.url || item.command}
                        </small>
                      </span>
                      <button
                        type="button"
                        aria-label={`${item.enabled ? "关闭" : "开启"} ${item.name}`}
                        className={`toggle ${item.enabled ? "on" : ""}`}
                        disabled={saving === `mcp:${item.id}`}
                        onClick={() => void toggleMcp(item)}
                      >
                        <i />
                      </button>
                    </div>
                  ))
                ) : (
                  <p className="capability-empty">还没有配置连接器。</p>
                ))}
            </>
          )}
          {error && <p className="capability-error">{error}</p>}
        </div>
      )}
    </div>
  );
}
