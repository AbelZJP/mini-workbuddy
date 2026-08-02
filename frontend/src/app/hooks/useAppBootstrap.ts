import { useCallback, useEffect } from "react";
import { json } from "../api";
import type { Model, Task, Workspace } from "../types";

type AppBootstrapOptions = {
  workspaceId: string;
  setWorkspaceId: (value: string) => void;
  setWorkspaces: React.Dispatch<React.SetStateAction<Workspace[]>>;
  setTasksByWorkspace: React.Dispatch<
    React.SetStateAction<Record<string, Task[]>>
  >;
  setModels: React.Dispatch<React.SetStateAction<Model[]>>;
  setModelId: (value: string) => void;
  setError: (value: string) => void;
};

export function useAppBootstrap(options: AppBootstrapOptions) {
  const {
    workspaceId,
    setWorkspaceId,
    setWorkspaces,
    setTasksByWorkspace,
    setModels,
    setModelId,
    setError,
  } = options;

  const refresh = useCallback(async () => {
    try {
      const [workspaces, models] = await Promise.all([
        json<Workspace[]>("/api/workspaces"),
        json<Model[]>("/api/models"),
      ]);
      const taskEntries = await Promise.all(
        workspaces.map(
          async (workspace) =>
            [
              workspace.id,
              await json<Task[]>(`/api/workspaces/${workspace.id}/tasks`),
            ] as const,
        ),
      );
      setWorkspaces(workspaces);
      setTasksByWorkspace(Object.fromEntries(taskEntries));
      setModels(models);
      setModelId(
        models.find((item) => item.is_default)?.id || models[0]?.id || "demo",
      );
      if (!workspaces.some((item) => item.id === workspaceId)) {
        setWorkspaceId(workspaces[0]?.id || "");
      }
    } catch (error) {
      setError(String(error));
    }
  }, [
    setError,
    setModelId,
    setModels,
    setTasksByWorkspace,
    setWorkspaceId,
    setWorkspaces,
    workspaceId,
  ]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { refresh };
}
