import React, { useEffect, useMemo, useState } from "react";
import { api, json } from "../../app/api";
import type { Skill, SkillHubRanking, SkillHubSkill } from "../../app/types";
import {
  EmptyCard,
  ManagementShell,
  ThemeSelect,
} from "../../components/common";

export function formatCount(value = 0) {
  if (value >= 1000000)
    return `${(value / 1000000).toFixed(1).replace(".0", "")}m`;
  if (value >= 1000) return `${(value / 1000).toFixed(1).replace(".0", "")}k`;
  return String(value);
}
export function skillKey(item: SkillHubSkill) {
  return item.namespace && item.namespace !== "global"
    ? `${item.namespace}/${item.slug}`
    : item.slug;
}

export function SkillsPage() {
  const [page, setPage] = useState<"store" | "installed">("store");
  return page === "installed" ? (
    <SkillHubInstalledPage onBack={() => setPage("store")} />
  ) : (
    <SkillHubStorePage onOpenInstalled={() => setPage("installed")} />
  );
}

export function cleanSkillHubError(error: unknown) {
  return String(error)
    .replace(/^Error:\s*/, "")
    .replace(/^"|"$/g, "");
}

export function SkillHubStorePage({
  onOpenInstalled,
}: {
  onOpenInstalled: () => void;
}) {
  const [items, setItems] = useState<SkillHubSkill[]>([]);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const [ranking, setRanking] = useState("all");
  const sort = "rating";
  const [categories, setCategories] = useState<{ id: string; name: string }[]>(
    [],
  );
  const [rankings, setRankings] = useState<SkillHubRanking[]>([]);
  const [installedCount, setInstalledCount] = useState(0);
  const [selected, setSelected] = useState<SkillHubSkill | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [loading, setLoading] = useState(false);
  const [installingId, setInstallingId] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState("");
  const pageSize = 24;
  const refreshInstalledCount = () =>
    json<{ totalElements: number }>("/api/skillhub/installed")
      .then((data) => setInstalledCount(data.totalElements))
      .catch(() => undefined);
  const load = async (nextPage = 0, append = false) => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({
        q: query,
        category,
        ranking: ranking === "all" ? "" : ranking,
        sort,
        page: String(nextPage),
        size: String(pageSize),
      });
      const data = await json<{
        content: SkillHubSkill[];
        totalElements: number;
      }>(`/api/skillhub/skills?${params.toString()}`);
      setItems((current) =>
        append ? [...current, ...(data.content || [])] : data.content || [],
      );
      setPage(nextPage);
      setTotal(data.totalElements || 0);
    } catch (e) {
      setError(cleanSkillHubError(e));
      if (!append) setItems([]);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    Promise.all([
      json<{ id: string; name: string }[]>("/api/skillhub/categories"),
      json<SkillHubRanking[]>("/api/skillhub/rankings"),
    ])
      .then(([categoryItems, rankingItems]) => {
        setCategories(categoryItems);
        setRankings(rankingItems);
      })
      .catch(() => {
        setCategories([
          { id: "all", name: "全部" },
          { id: "office-efficiency", name: "办公效率" },
          { id: "content-creation", name: "内容创作" },
          { id: "dev-programming", name: "开发编程" },
          { id: "data-analysis", name: "数据分析" },
          { id: "design-media", name: "设计多媒体" },
          { id: "ai-agent", name: "AI Agent" },
          { id: "knowledge-management", name: "知识管理" },
          { id: "business-ops", name: "商业运营" },
          { id: "education", name: "教育学系" },
          { id: "professional", name: "行业专业" },
          { id: "it-ops-security", name: "IT运维与安全" },
          { id: "life-service", name: "生活服务" },
        ]);
        setRankings([
          { id: "featured", name: "推荐精选" },
          { id: "trending", name: "近期飙升" },
          { id: "downloads", name: "下载量" },
          { id: "favorites", name: "收藏量" },
        ]);
      });
    refreshInstalledCount();
  }, []);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load(0, false);
    }, 220);
    return () => window.clearTimeout(timer);
  }, [query, category, ranking]);
  const install = async (item: SkillHubSkill) => {
    if (installingId) return;
    setInstallingId(item.id);
    setError("");
    try {
      await json("/api/skillhub/install", {
        method: "POST",
        body: JSON.stringify({ coordinate: skillKey(item) }),
      });
      setItems((current) =>
        current.map((entry) =>
          entry.id === item.id ? { ...entry, installed: true } : entry,
        ),
      );
      setSelected((current) =>
        current?.id === item.id ? { ...current, installed: true } : current,
      );
      refreshInstalledCount();
    } catch (e) {
      setError(`安装失败：${cleanSkillHubError(e)}`);
    } finally {
      setInstallingId(null);
    }
  };
  const availableCategories = categories.length
    ? categories
    : [{ id: "all", name: "全部" }];
  const availableRankings = rankings.length
    ? rankings
    : [
        { id: "featured", name: "推荐精选" },
        { id: "trending", name: "近期飙升" },
        { id: "downloads", name: "下载量" },
        { id: "favorites", name: "收藏量" },
      ];
  const canLoadMore = items.length < total;
  return (
    <section className="skillhub-page">
      <header className="skillhub-header">
        <div className="skillhub-heading">
          <span className="eyebrow">SKILL MARKET</span>
          <h1>技能</h1>
          <p>从 SkillHub 发现并安装可复用的 Agent Skills</p>
        </div>
        <div className="skillhub-actions">
          <label className="skillhub-search">
            <span>⌕</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索技能"
            />
            <kbd>⌘ K</kbd>
          </label>
          <button className="hub-top-button" onClick={onOpenInstalled}>
            ▣ 我安装的 <b>{installedCount}</b>
          </button>
          <button className="hub-add-button" onClick={() => setShowAdd(true)}>
            ⊕ 添加技能
          </button>
        </div>
      </header>
      <section className="skillhub-catalog skillhub-catalog-only">
        <div className="skillhub-category-heading">
          <div>
            <span className="eyebrow">SKILLHUB CATALOG</span>
            <h2>技能市场</h2>
          </div>
          <small>
            {loading
              ? "正在同步…"
              : `${items.length}${total ? ` / ${total}` : ""} 项技能`}
          </small>
        </div>
        <div className="skillhub-ranking-row">
          <button
            className={ranking === "all" ? "active" : ""}
            onClick={() => setRanking("all")}
          >
            全部
          </button>
          {availableRankings.map((item) => (
            <button
              key={item.id}
              className={ranking === item.id ? "active" : ""}
              title={item.description}
              onClick={() => setRanking(item.id)}
            >
              {item.name}
            </button>
          ))}
        </div>
        <div className="skillhub-filter-line">
          <a
            className="skillhub-source-link"
            href="https://skillhub.cn/"
            target="_blank"
            rel="noreferrer"
          >
            ↗ skillhub.cn
          </a>
          <div className="skillhub-sort">
            <ThemeSelect
              label="场景"
              value={category}
              onChange={setCategory}
              options={availableCategories.map((item) => ({
                value: item.id,
                label: item.name,
              }))}
            />
          </div>
        </div>
        {error && <div className="skillhub-error">{error}</div>}
        <div className="skillhub-grid">
          {items.length
            ? items.map((item) => (
                <SkillHubCard
                  key={`${item.id}-${item.latestVersion || ""}`}
                  item={item}
                  installing={installingId === item.id}
                  onOpen={() => setSelected(item)}
                  onInstall={() => void install(item)}
                />
              ))
            : !loading && (
                <div className="skillhub-empty">没有找到匹配的技能。</div>
              )}
        </div>
        {canLoadMore && (
          <button
            className="skillhub-load-more"
            disabled={loading || Boolean(installingId)}
            onClick={() => void load(page + 1, true)}
          >
            {loading
              ? "正在加载…"
              : `加载更多（还剩 ${Math.max(total - items.length, 0)} 个）`}
          </button>
        )}
      </section>
      {selected && (
        <SkillHubDetail
          item={selected}
          installing={Boolean(installingId)}
          onClose={() => setSelected(null)}
          onInstall={() => void install(selected)}
        />
      )}
      {showAdd && (
        <SkillHubAddModal
          onClose={() => setShowAdd(false)}
          onInstalled={() => {
            setShowAdd(false);
            refreshInstalledCount();
            void load(0, false);
          }}
        />
      )}
    </section>
  );
}

export function SkillHubInstalledPage({ onBack }: { onBack: () => void }) {
  const [items, setItems] = useState<SkillHubSkill[]>([]);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<SkillHubSkill | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [loading, setLoading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({
        q: query,
        installed: "true",
        size: "100",
      });
      const data = await json<{ content: SkillHubSkill[] }>(
        `/api/skillhub/skills?${params.toString()}`,
      );
      setItems(data.content || []);
    } catch (e) {
      setError(cleanSkillHubError(e));
      setItems([]);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 180);
    return () => window.clearTimeout(timer);
  }, [query]);
  const remove = async (item: SkillHubSkill) => {
    if (
      !window.confirm(
        `确定删除技能“${item.name}”？这会移除项目 skills 目录中的技能文件。`,
      )
    )
      return;
    setDeletingId(item.id);
    setError("");
    try {
      await api(`/api/skills/${encodeURIComponent(item.id)}`, {
        method: "DELETE",
      });
      setItems((current) => current.filter((entry) => entry.id !== item.id));
      setSelected(null);
    } catch (e) {
      setError(cleanSkillHubError(e));
    } finally {
      setDeletingId(null);
    }
  };
  return (
    <section className="skillhub-page">
      <header className="skillhub-header skillhub-installed-header">
        <div className="skillhub-heading">
          <button className="hub-back-button" onClick={onBack}>
            ← 返回 SkillHub
          </button>
          <span className="eyebrow">MY SKILLS</span>
          <h1>我安装的</h1>
          <p>管理已经安装到当前项目的本地 Skills</p>
        </div>
        <div className="skillhub-actions">
          <label className="skillhub-search">
            <span>⌕</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索已安装技能"
            />
          </label>
          <button className="hub-add-button" onClick={() => setShowAdd(true)}>
            ⊕ 添加技能
          </button>
        </div>
      </header>
      <section className="skillhub-catalog skillhub-installed-catalog">
        <div className="skillhub-category-heading">
          <div>
            <span className="eyebrow">LOCAL SKILLS</span>
            <h2>已安装技能</h2>
          </div>
          <small>{loading ? "正在读取…" : `${items.length} 项`}</small>
        </div>
        {error && <div className="skillhub-error">{error}</div>}
        <div className="skillhub-grid">
          {items.length
            ? items.map((item) => (
                <SkillHubCard
                  key={item.id}
                  item={item}
                  deleting={deletingId === item.id}
                  onOpen={() => setSelected(item)}
                  onInstall={() => undefined}
                  onDelete={() => void remove(item)}
                />
              ))
            : !loading && (
                <div className="skillhub-empty">
                  还没有安装技能，点击右上角“添加技能”开始安装。
                </div>
              )}
        </div>
      </section>
      {selected && (
        <SkillHubDetail
          item={selected}
          deleting={deletingId === selected.id}
          onClose={() => setSelected(null)}
          onInstall={() => undefined}
          onDelete={() => void remove(selected)}
        />
      )}
      {showAdd && (
        <SkillHubAddModal
          onClose={() => setShowAdd(false)}
          onInstalled={() => {
            setShowAdd(false);
            void load();
          }}
        />
      )}
    </section>
  );
}

export function SkillHubCard({
  item,
  featured = false,
  installing = false,
  deleting = false,
  onOpen,
  onInstall,
  onDelete,
}: {
  item: SkillHubSkill;
  featured?: boolean;
  installing?: boolean;
  deleting?: boolean;
  onOpen: () => void;
  onInstall: () => void;
  onDelete?: () => void;
}) {
  const label =
    item.labels?.[0] || (item.source === "local" ? "已安装" : "SkillHub");
  const local = item.source === "local";
  return (
    <article
      className={`skillhub-card ${featured ? "featured" : ""}`}
      onClick={onOpen}
    >
      <div className="skillhub-card-head">
        <div className="skillhub-icon">✦</div>
        <div className="skillhub-card-title">
          <h3 title={item.name}>{item.name}</h3>
          <span>
            {item.namespace && item.namespace !== "global"
              ? `${item.namespace} / `
              : ""}
            {item.slug}
          </span>
        </div>
        {local ? (
          <button
            disabled={deleting}
            className="skillhub-delete"
            title={deleting ? "删除中" : "删除技能"}
            onClick={(event) => {
              event.stopPropagation();
              if (!deleting) onDelete?.();
            }}
          >
            {deleting ? "…" : "×"}
          </button>
        ) : (
          <button
            disabled={installing}
            className={`skillhub-install ${item.installed ? "installed" : ""}`}
            title={
              installing ? "安装中" : item.installed ? "已安装" : "安装技能"
            }
            onClick={(event) => {
              event.stopPropagation();
              if (!item.installed && !installing) onInstall();
            }}
          >
            {item.installed ? "✓" : installing ? "…" : "+"}
          </button>
        )}
      </div>
      <p>{item.description || "暂无技能描述"}</p>
      <div className="skillhub-card-meta">
        <span>↓ {formatCount(item.downloads)}</span>
        <span>☆ {item.starCount || item.rating || 0}</span>
        <em>{label}</em>
      </div>
    </article>
  );
}

export function SkillHubDetail({
  item,
  installing = false,
  deleting = false,
  onClose,
  onInstall,
  onDelete,
}: {
  item: SkillHubSkill;
  installing?: boolean;
  deleting?: boolean;
  onClose: () => void;
  onInstall: () => void;
  onDelete?: () => void;
}) {
  const local = item.source === "local";
  return (
    <div className="modal-backdrop">
      <div className="modal wide skillhub-detail-modal">
        <div className="modal-head">
          <div>
            <span className="eyebrow">SKILLHUB SKILL</span>
            <h2>{item.name}</h2>
          </div>
          <button onClick={onClose}>×</button>
        </div>
        <p className="skillhub-detail-description">
          {item.description || "暂无技能描述"}
        </p>
        <div className="skillhub-detail-meta">
          <span>标识：{skillKey(item)}</span>
          <span>版本：{item.latestVersion || "latest"}</span>
          <span>下载：{formatCount(item.downloads)}</span>
        </div>
        <pre className="detail-content">{`安装后会写入项目 skills/ 目录，并自动纳入当前 Skills 扫描和 Agent 上下文。\n\n来源：${local ? "本地技能" : "SkillHub 公开注册中心"}`}</pre>
        <div className="modal-actions">
          <button className="secondary-button" onClick={onClose}>
            关闭
          </button>
          {local ? (
            <button
              className="danger-button"
              disabled={deleting}
              onClick={onDelete}
            >
              {deleting ? "删除中…" : "删除技能"}
            </button>
          ) : (
            <button
              className="primary-button"
              disabled={item.installed || installing}
              onClick={onInstall}
            >
              {item.installed ? "已安装" : installing ? "安装中…" : "安装技能"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export function SkillHubAddModal({
  onClose,
  onInstalled,
}: {
  onClose: () => void;
  onInstalled: () => void;
}) {
  const [coordinate, setCoordinate] = useState("");
  const [version, setVersion] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const install = async () => {
    if (!coordinate.trim()) {
      setError(
        "请输入技能名称、命名空间/技能名、SkillHub 链接或 skills.sh 链接",
      );
      return;
    }
    setSaving(true);
    setError("");
    try {
      await json("/api/skillhub/install", {
        method: "POST",
        body: JSON.stringify({
          coordinate: coordinate.trim(),
          version: version.trim(),
        }),
      });
      onInstalled();
    } catch (e) {
      setError(String(e).replace(/^Error:\s*/, ""));
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="modal-backdrop">
      <div className="modal">
        <div className="modal-head">
          <div>
            <span className="eyebrow">ADD SKILL</span>
            <h2>添加技能</h2>
          </div>
          <button onClick={onClose}>×</button>
        </div>
        <label>
          技能名称或详情链接
          <input
            autoFocus
            value={coordinate}
            onChange={(event) => setCoordinate(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void install();
            }}
            placeholder="例如 pdf-parser 或 https://www.skills.sh/anthropics/skills/pptx"
          />
        </label>
        <label>
          版本（可选）
          <input
            value={version}
            onChange={(event) => setVersion(event.target.value)}
            placeholder="SkillHub 支持填写；skills.sh 无需填写"
          />
        </label>
        <p className="modal-note">
          腾讯 SkillHub 技能使用 SkillHub CLI；skills.sh 技能使用官方 skills
          CLI，并复制到当前项目的 skills/ 目录，安装后会出现在“我安装的”。
        </p>
        {error && <p className="modal-error">{error}</p>}
        <div className="modal-actions">
          <button className="secondary-button" onClick={onClose}>
            取消
          </button>
          <button
            className="primary-button"
            disabled={saving}
            onClick={() => void install()}
          >
            {saving ? "安装中…" : "安装技能"}
          </button>
        </div>
      </div>
    </div>
  );
}
