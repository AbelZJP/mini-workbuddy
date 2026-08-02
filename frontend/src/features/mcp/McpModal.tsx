import React, { useState } from "react";
import { json } from "../../app/api";

export function McpModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  type EnvironmentEntry = { key: string; envName: string };
  const [form, setForm] = useState({
    id: `mcp-${Date.now()}`,
    name: "新连接器",
    transport: "stdio",
    command: "npx",
    args: ["-y"],
    url: "",
    envEntries: [{ key: "", envName: "" }] as EnvironmentEntry[],
    headers_text: "",
  });
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState("");
  const [testResult, setTestResult] = useState<{
    ok: boolean;
    text: string;
  } | null>(null);
  const [formVersion, setFormVersion] = useState(0);
  const [testedVersion, setTestedVersion] = useState(-1);
  const update = (key: string, value: string) => {
    setForm((current) => ({ ...current, [key]: value }));
    setFormVersion((current) => current + 1);
    setTestedVersion(-1);
    setTestResult(null);
    setError("");
  };
  const updateArgs = (value: string) => {
    setForm((current) => ({
      ...current,
      args: value.split(" ").filter(Boolean),
    }));
    setFormVersion((current) => current + 1);
    setTestedVersion(-1);
    setTestResult(null);
    setError("");
  };
  const updateEnvironment = (
    index: number,
    field: keyof EnvironmentEntry,
    value: string,
  ) => {
    setForm((current) => ({
      ...current,
      envEntries: current.envEntries.map((entry, entryIndex) =>
        entryIndex === index ? { ...entry, [field]: value } : entry,
      ),
    }));
    setFormVersion((current) => current + 1);
    setTestedVersion(-1);
    setTestResult(null);
    setError("");
  };
  const addEnvironment = () => {
    setForm((current) => ({
      ...current,
      envEntries: [...current.envEntries, { key: "", envName: "" }],
    }));
    setFormVersion((current) => current + 1);
    setTestedVersion(-1);
    setTestResult(null);
  };
  const removeEnvironment = (index: number) => {
    setForm((current) => ({
      ...current,
      envEntries:
        current.envEntries.length === 1
          ? [{ key: "", envName: "" }]
          : current.envEntries.filter((_, entryIndex) => entryIndex !== index),
    }));
    setFormVersion((current) => current + 1);
    setTestedVersion(-1);
    setTestResult(null);
  };
  const buildPayload = () => {
    let headers: Record<string, string> = {};
    if (form.transport === "streamable_http" && form.headers_text.trim()) {
      try {
        const parsed = JSON.parse(form.headers_text);
        if (!parsed || Array.isArray(parsed) || typeof parsed !== "object")
          throw new Error();
        headers = Object.fromEntries(
          Object.entries(parsed).map(([key, value]) => [key, String(value)]),
        );
      } catch {
        setError(
          'Headers JSON 格式不正确，请填写对象，例如 {"Authorization":"Bearer ${TOKEN}"}',
        );
        return null;
      }
    }
    const env: Record<string, string> = {};
    for (const entry of form.envEntries) {
      const key = entry.key.trim();
      const envName = (entry.envName || entry.key).trim();
      if (!key && !envName) continue;
      if (!key || !envName) {
        setError("环境变量的 MCP 变量名和 .env 变量名都不能为空");
        return null;
      }
      if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key) || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(envName)) {
        setError("环境变量名只能包含字母、数字和下划线，且不能以数字开头");
        return null;
      }
      env[key] = "${" + envName + "}";
    }
    return {
      id: form.id,
      name: form.name,
      transport: form.transport,
      command: form.transport === "stdio" ? form.command : "",
      args: form.transport === "stdio" ? form.args : [],
      url: form.transport === "stdio" ? "" : form.url,
      enabled: false,
      allowed_tools: [],
      env: form.transport === "stdio" ? env : {},
      headers,
    };
  };
  const testConfig = async () => {
    const payload = buildPayload();
    if (!payload) return;
    setTesting(true);
    setError("");
    setTestResult(null);
    try {
      const data = await json<{
        ok: boolean;
        count?: number;
        tools?: string[];
        error?: string;
      }>("/api/mcp/test", { method: "POST", body: JSON.stringify(payload) });
      if (data.ok) {
        setTestedVersion(formVersion);
        setTestResult({
          ok: true,
          text: `连接成功：发现 ${data.count || 0} 个工具${data.tools?.length ? `\n${data.tools.join(", ")}` : ""}`,
        });
      } else
        setTestResult({
          ok: false,
          text: `连接失败：${data.error || "MCP 服务未通过测试"}`,
        });
    } catch (e) {
      setTestResult({
        ok: false,
        text: `连接失败：${String(e).replace(/^Error:\s*/, "")}`,
      });
    } finally {
      setTesting(false);
    }
  };
  const save = async () => {
    if (testedVersion !== formVersion) {
      setError("请先测试当前配置，测试通过后才能保存");
      return;
    }
    const payload = buildPayload();
    if (!payload) return;
    setSaving(true);
    setError("");
    try {
      await json("/api/mcp", { method: "POST", body: JSON.stringify(payload) });
      onCreated();
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
          <h2>添加 MCP 连接器</h2>
          <button onClick={onClose}>×</button>
        </div>
        <label>
          名称
          <input
            value={form.name}
            onChange={(event) => update("name", event.target.value)}
          />
        </label>
        <label>
          传输
          <select
            value={form.transport}
            onChange={(event) => update("transport", event.target.value)}
          >
            <option value="stdio">stdio</option>
            <option value="streamable_http">Streamable HTTP</option>
            <option value="sse">SSE</option>
          </select>
        </label>
        {form.transport === "stdio" ? (
          <>
            <label>
              命令
              <input
                value={form.command}
                onChange={(event) => update("command", event.target.value)}
              />
            </label>
            <label>
              参数（空格分隔）
              <input
                value={form.args.join(" ")}
                onChange={(event) => updateArgs(event.target.value)}
              />
            </label>
            <div className="mcp-env-section">
              <div className="mcp-env-title">
                <span>环境变量（可选）</span>
                <button
                  type="button"
                  className="text-button"
                  onClick={addEnvironment}
                >
                  ＋ 添加变量
                </button>
              </div>
              {form.envEntries.map((entry, index) => (
                <div className="mcp-env-row" key={index}>
                  <input
                    value={entry.key}
                    onChange={(event) =>
                      updateEnvironment(index, "key", event.target.value)
                    }
                    placeholder="MCP 变量名"
                  />
                  <span>←</span>
                  <input
                    value={entry.envName}
                    onChange={(event) =>
                      updateEnvironment(index, "envName", event.target.value)
                    }
                    placeholder=".env 变量名"
                  />
                  <button
                    type="button"
                    className="mcp-env-remove"
                    title="移除环境变量"
                    onClick={() => removeEnvironment(index)}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
            <p className="modal-note compact-note">
              MCP 变量名可以和项目 .env 变量名不同；实际值从项目 .env 读取，数据库只保存变量引用。
            </p>
          </>
        ) : (
          <>
            <label>
              URL
              <input
                value={form.url}
                onChange={(event) => update("url", event.target.value)}
              />
            </label>
            {form.transport === "streamable_http" && (
              <>
                <label>
                  Headers 请求头 JSON（可选）
                  <textarea
                    className="mcp-headers-textarea"
                    value={form.headers_text}
                    onChange={(event) =>
                      update("headers_text", event.target.value)
                    }
                    placeholder={
                      '例如：\n{\n  "Authorization": "Bearer ${TOKEN}"\n}'
                    }
                  />
                </label>
                <p className="modal-note compact-note">
                  支持使用 ${"{TOKEN}"} 引用项目 .env 中的环境变量。
                </p>
              </>
            )}
          </>
        )}{" "}
        {testResult && (
          <div
            className={`mcp-test-result ${testResult.ok ? "success" : "failure"}`}
          >
            {testResult.text}
          </div>
        )}
        {error && <p className="modal-error">{error}</p>}
        <div className="modal-actions">
          <button className="secondary-button" onClick={onClose}>
            取消
          </button>
          <button
            className="secondary-button"
            disabled={testing || saving}
            onClick={() => void testConfig()}
          >
            {testing ? "测试中…" : "测试连接"}
          </button>
          <button
            className="primary-button"
            disabled={saving || testing || testedVersion !== formVersion}
            onClick={() => void save()}
          >
            {saving
              ? "保存中…"
              : testedVersion === formVersion
                ? "保存连接器"
                : "测试通过后保存"}
          </button>
        </div>
      </div>
    </div>
  );
}
