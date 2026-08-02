import { json } from "../api";
import type { Task } from "../types";

type CapabilitiesOptions = {
  taskId: string;
  workspaceId: string;
  setTasksByWorkspace: React.Dispatch<
    React.SetStateAction<Record<string, Task[]>>
  >;
  setError: (value: string) => void;
};

export function useCapabilities(options: CapabilitiesOptions) {
  const { taskId, workspaceId, setTasksByWorkspace, setError } = options;

  const updateTaskCapabilities = async (
    skillIds: string[],
    expertIds: string[],
  ) => {
    if (!taskId) return;
    try {
      const updated = await json<Task>(`/api/tasks/${taskId}/capabilities`, {
        method: "PATCH",
        body: JSON.stringify({
          selected_skill_ids: skillIds,
          selected_expert_ids: expertIds,
        }),
      });
      setTasksByWorkspace((current) => ({
        ...current,
        [workspaceId]: (current[workspaceId] || []).map((item) =>
          item.id === updated.id ? updated : item,
        ),
      }));
    } catch (error) {
      setError(`更新任务能力失败：${String(error).replace(/^Error:\\s*/, "")}`);
    }
  };

  return { updateTaskCapabilities };
}
