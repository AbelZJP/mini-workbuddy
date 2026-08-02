import React, { useEffect, useMemo, useState } from "react";
import { api, json } from "../../app/api";
import type { Expert, ExpertResponse } from "../../app/types";
import { EmptyCard, ManagementShell } from "../../components/common";

export function ExpertsPage() {
  const [items, setItems] = useState<Expert[]>([]);
  const [departments, setDepartments] = useState<string[]>([]);
  const [repository, setRepository] = useState(
    "https://github.com/jnMetaCode/agency-agents-zh",
  );
  const [synced, setSynced] = useState(false);
  const [query, setQuery] = useState("");
  const [department, setDepartment] = useState("全部");
  const [installedOnly, setInstalledOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [changingId, setChangingId] = useState("");
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Expert | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (query.trim()) params.set("query", query.trim());
      if (department !== "全部") params.set("department", department);
      if (installedOnly) params.set("installed", "true");
      const data = await json<ExpertResponse>(
        `/api/experts${params.size ? `?${params}` : ""}`,
      );
      setItems(data.items);
      setDepartments(data.departments);
      setRepository(data.repository);
      setSynced(data.synced);
      setError("");
    } catch (e) {
      setError(`读取专家库失败：${String(e).replace(/^Error:\s*/, "")}`);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void load();
  }, [query, department, installedOnly]);
  const sync = async () => {
    setSyncing(true);
    setError("");
    try {
      await json<ExpertResponse>("/api/experts/sync", { method: "POST" });
      await load();
    } catch (e) {
      setError(`同步专家库失败：${String(e).replace(/^Error:\s*/, "")}`);
    } finally {
      setSyncing(false);
    }
  };
  const changeInstall = async (expert: Expert) => {
    setChangingId(expert.id);
    setError("");
    try {
      if (expert.installed)
        await api(`/api/experts/${encodeURIComponent(expert.id)}`, {
          method: "DELETE",
        });
      else
        await api(`/api/experts/${encodeURIComponent(expert.id)}/install`, {
          method: "POST",
        });
      await load();
    } catch (e) {
      setError(
        `${expert.installed ? "卸载" : "安装"}专家失败：${String(e).replace(/^Error:\s*/, "")}`,
      );
    } finally {
      setChangingId("");
    }
  };
  const installedCount = items.filter((item) => item.installed).length;
  const openInstalled = () => {
    setInstalledOnly(true);
    setDepartment("全部");
    setQuery("");
  };
  const backToCatalog = () => {
    setInstalledOnly(false);
    setDepartment("全部");
    setQuery("");
  };
  return (
    <section className="experts-page">
      <header
        className={`experts-header ${installedOnly ? "experts-installed-header" : ""}`}
      >
        <div className="experts-heading">
          {installedOnly && (
            <button className="hub-back-button" onClick={backToCatalog}>
              ← 返回专家库
            </button>
          )}
          <span className="eyebrow">
            {installedOnly ? "MY EXPERTS" : "AGENCY DIRECTORY"}
          </span>
          <h1>{installedOnly ? "已安装专家" : "专家库"}</h1>
          <p>
            {installedOnly
              ? "管理已安装到本项目的专家角色提示词。"
              : "浏览并安装专业角色，安装后保存在本项目独立专家目录。"}
          </p>
        </div>
        <div className="experts-actions">
          <label className="skillhub-search">
            <span>⌕</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={installedOnly ? "搜索已安装专家" : "搜索专家角色"}
            />
          </label>
          {!installedOnly && (
            <button className="hub-top-button" onClick={openInstalled}>
              ▣ 已安装 <b>{installedCount}</b>
            </button>
          )}
          <button
            className="hub-add-button"
            disabled={syncing}
            onClick={() => void sync()}
          >
            {syncing ? "同步中…" : synced ? "↻ 同步专家库" : "↓ 下载专家库"}
          </button>
        </div>
      </header>
      <section
        className={`experts-catalog ${installedOnly ? "experts-installed-catalog" : ""}`}
      >
        <div className="experts-catalog-head">
          <div>
            <span className="eyebrow">
              {installedOnly ? "LOCAL EXPERTS" : "OPEN ROLE LIBRARY"}
            </span>
            <h2>{installedOnly ? "已安装专家" : "全部专家"}</h2>
          </div>
          {!installedOnly && (
            <a href={repository} target="_blank" rel="noreferrer">
              ↗ 查看来源
            </a>
          )}
        </div>
        {!installedOnly && (
          <div className="experts-filter-row">
            <button
              className={department === "全部" ? "active" : ""}
              onClick={() => setDepartment("全部")}
            >
              全部
            </button>
            {departments.map((item) => (
              <button
                key={item}
                className={department === item ? "active" : ""}
                onClick={() => setDepartment(item)}
              >
                {item}
              </button>
            ))}
          </div>
        )}
        {error && <div className="skillhub-error">{error}</div>}
        <div className="experts-grid">
          {loading ? (
            <div className="skillhub-empty">正在读取专家库…</div>
          ) : items.length ? (
            items.map((item) => (
              <article
                className="expert-card"
                key={item.id}
                onClick={() => setSelected(item)}
              >
                <div className="expert-card-top">
                  <div className="expert-avatar">
                    {item.department.slice(0, 1)}
                  </div>
                  <div className="expert-title">
                    <span>{item.department}</span>
                    <h3 title={item.name}>{item.name}</h3>
                  </div>
                  <button
                    className={`expert-install ${item.installed ? "installed" : ""}`}
                    disabled={changingId === item.id}
                    title={item.installed ? "卸载专家" : "安装专家"}
                    onClick={(event) => {
                      event.stopPropagation();
                      void changeInstall(item);
                    }}
                  >
                    {changingId === item.id ? "…" : item.installed ? "✓" : "+"}
                  </button>
                </div>
                <p>
                  {item.description ||
                    "该角色提供专业工作流、交付物模板和领域实践建议。"}
                </p>
                <div className="expert-card-footer">
                  <code>{item.catalog_path}</code>
                  <span>
                    {item.installed ? "已安装到本地" : "点击查看提示词"}
                  </span>
                </div>
              </article>
            ))
          ) : (
            <div className="skillhub-empty">
              {installedOnly
                ? "暂未安装专家。返回专家库选择需要的角色。"
                : synced
                  ? "没有找到匹配的专家角色。"
                  : "尚未下载专家库。点击右上角“下载专家库”开始同步。"}
            </div>
          )}
        </div>
      </section>
      {selected && (
        <ExpertDetailModal
          expert={selected}
          onClose={() => setSelected(null)}
        />
      )}
    </section>
  );
}

export function ExpertDetailModal({
  expert,
  onClose,
}: {
  expert: Expert;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<(Expert & { content: string }) | null>(
    null,
  );
  const [error, setError] = useState("");
  useEffect(() => {
    json<Expert & { content: string }>(
      `/api/experts/${encodeURIComponent(expert.id)}`,
    )
      .then(setDetail)
      .catch((reason) => setError(String(reason).replace(/^Error:\s*/, "")));
  }, [expert.id]);
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div
        className="modal wide expert-detail-modal"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="modal-head">
          <div>
            <span className="eyebrow">EXPERT PROMPT</span>
            <h2>{expert.name}</h2>
          </div>
          <button onClick={onClose} aria-label="关闭专家提示词">
            ×
          </button>
        </div>
        <div className="expert-detail-meta">
          <span>{expert.department}</span>
          <code>{expert.catalog_path}</code>
        </div>
        {error ? (
          <div className="skillhub-error">读取提示词失败：{error}</div>
        ) : (
          <pre className="detail-content">
            {detail ? detail.content : "正在加载专家提示词…"}
          </pre>
        )}
        <div className="modal-actions">
          <button className="secondary-button" onClick={onClose}>
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}
