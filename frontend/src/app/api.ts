export const api = async (path: string, options?: RequestInit) => {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) throw new Error(await response.text());
  return response;
};

export const json = async <T>(
  path: string,
  options?: RequestInit,
): Promise<T> => (await api(path, options)).json();

export const taskTitleFromMessage = (value: string) => {
  const clean = value
    .replace(/\s+/g, " ")
    .split("附件（已复制到当前工作空间）：", 1)[0]
    .trim();
  return clean.length > 18 ? clean.slice(0, 18) + "…" : clean || "新任务";
};

export const loadCapabilities = () =>
  json<{ items: import("./types").Capability[] }>('/api/capabilities');

export const loadCapabilityModels = (capabilityId: string) =>
  json<import("./types").CapabilityModelOption[]>(
    `/api/capabilities/${encodeURIComponent(capabilityId)}/models`,
  );

export const updateCapabilityModel = (capabilityId: string, modelId: string) =>
  json(`/api/capabilities/${encodeURIComponent(capabilityId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ model_id: modelId }),
  });
