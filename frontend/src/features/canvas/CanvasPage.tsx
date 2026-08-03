import {
  Background,
  BackgroundVariant,
  ConnectionLineType,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type NodeProps,
  type ReactFlowInstance,
  type Viewport,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { json } from "../../app/api";
import type {
  CanvasGraph,
  CanvasNodeKind,
  CanvasProject,
  Model,
} from "../../app/types";

type CanvasNodeData = {
  title: string;
  kind: CanvasNodeKind;
  config: Record<string, string>;
  models?: Model[];
  status?: "idle" | "running" | "success" | "error";
  onChange?: (id: string, patch: Record<string, string>) => void;
  onRemove?: (id: string) => void;
  onUpload?: (id: string, file: File) => void;
  onPolish?: (id: string) => void;
  onGenerate?: (id: string) => void;
  onQuickAdd?: (sourceId: string, kind: CanvasNodeKind) => void;
  onFrameImage?: (sourceId: string, time: number) => void;
  previewUrl?: string;
};
type CanvasNode = Node<CanvasNodeData, CanvasNodeKind>;
type CanvasEdge = Edge;
type PersistedNode = CanvasGraph["nodes"][number];
type FramePreview = { time: number; url: string };

const PREVIEW_FRAME_RATE = 1;
const MAX_FRAME_PREVIEWS = 180;

const NODE_META: Record<
  CanvasNodeKind,
  { label: string; icon: string; description: string; className: string }
> = {
  text: {
    label: "文本节点",
    icon: "T",
    description: "输入提示词或脚本文本",
    className: "text",
  },
  "image-upload": {
    label: "图片上传",
    icon: "▧",
    description: "添加图片参考素材",
    className: "image",
  },
  "ai-image": {
    label: "AI 图片",
    icon: "✦",
    description: "生成或改写一张图片",
    className: "ai-image",
  },
  "video-upload": {
    label: "视频上传",
    icon: "▶",
    description: "添加视频参考素材",
    className: "video",
  },
  "ai-video": {
    label: "AI 视频",
    icon: "▰",
    description: "生成一段动态视频",
    className: "ai-video",
  },
  note: {
    label: "备注",
    icon: "✎",
    description: "记录创意、说明和待办",
    className: "note",
  },
};

const DEFAULT_CONFIG: Record<CanvasNodeKind, Record<string, string>> = {
  text: { content: "", model: "" },
  "image-upload": { fileName: "", filePath: "", fileUrl: "", contentType: "" },
  "ai-image": { prompt: "", ratio: "1:1", model: "", outputPath: "", outputUrl: "", outputFileName: "" },
  "video-upload": { fileName: "", filePath: "", fileUrl: "", contentType: "" },
  "ai-video": {
    prompt: "",
    ratio: "16:9",
    model: "",
    duration: "5s",
    resolution: "1080p",
    audio: "有声",
    outputPath: "",
    outputUrl: "",
    outputFileName: "",
  },
  note: { content: "" },
};

function makeNode(
  kind: CanvasNodeKind,
  position: { x: number; y: number },
  actions?: Pick<CanvasNodeData, "models" | "onChange" | "onRemove" | "onUpload" | "onPolish" | "onGenerate" | "onQuickAdd" | "onFrameImage">,
): CanvasNode {
  const meta = NODE_META[kind];
  return {
    id: `${kind}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    type: kind,
    position,
    data: {
      title: meta.label,
      kind,
      config: { ...DEFAULT_CONFIG[kind], scope: "direct" },
      status: "idle",
      ...actions,
    },
  };
}

function isCycle(edges: CanvasEdge[], connection: Connection) {
  if (!connection.source || !connection.target) return false;
  if (connection.source === connection.target) return true;
  const adjacency = new Map<string, string[]>();
  edges.forEach((edge) => {
    const next = adjacency.get(edge.source) || [];
    next.push(edge.target);
    adjacency.set(edge.source, next);
  });
  const seen = new Set<string>();
  const stack = [connection.target];
  while (stack.length) {
    const current = stack.pop()!;
    if (current === connection.source) return true;
    if (seen.has(current)) continue;
    seen.add(current);
    stack.push(...(adjacency.get(current) || []));
  }
  return false;
}

function nodeToPersisted(node: CanvasNode): PersistedNode {
  return {
    id: node.id,
    type: node.type || node.data.kind,
    position: node.position,
    data: {
      title: node.data.title,
      kind: node.data.kind,
      config: node.data.config,
      status: node.data.status || "idle",
    },
  };
}

function NodeShell({
  id,
  data,
  selected,
  children,
}: NodeProps<CanvasNode> & { children: React.ReactNode }) {
  const meta = NODE_META[data.kind];
  const [quickAddOpen, setQuickAddOpen] = useState(false);
  const quickAddWrapRef = useRef<HTMLDivElement>(null);
  const patch = (next: Record<string, string>) => data.onChange?.(id, next);
  const config = data.config;

  useEffect(() => {
    if (!quickAddOpen) return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      const target = event.target as HTMLElement | null;
      if (!quickAddWrapRef.current?.contains(target)) {
        setQuickAddOpen(false);
      }
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () => document.removeEventListener("pointerdown", closeOnOutsidePointer);
  }, [quickAddOpen]);

  return (
    <div className={`canvas-node ${meta.className} ${selected ? "selected" : ""}`}>
      <Handle className="canvas-handle" type="target" position={Position.Left} />
      <div className="canvas-node-head">
        <div className="canvas-node-icon">{meta.icon}</div>
        <div className="canvas-node-title">
          <span>{data.kind.replace("-", " ").toUpperCase()}</span>
          <strong>{data.title}</strong>
        </div>
        <button
          className="canvas-node-info"
          type="button"
          title={meta.description}
          onClick={() => window.alert(meta.description)}
        >
          i
        </button>
        <button
          className="canvas-node-close"
          type="button"
          title="删除节点"
          onClick={() => data.onRemove?.(id)}
        >
          ×
        </button>
      </div>
      <div className="canvas-node-body">{children}</div>
      <div className="canvas-node-footer">
        <button
          type="button"
          className={`canvas-direct ${config.scope === "global" ? "global" : "active"}`}
          title={config.scope === "global" ? "所有后续节点都会纳入本节点内容" : "仅直接连接的后续节点会纳入本节点内容"}
          onClick={() => patch({ scope: config.scope === "global" ? "direct" : "global" })}
        >
          {config.scope === "global" ? "全局" : "直连"}
        </button>
        {data.status && data.status !== "idle" && (
          <span className={`canvas-node-status ${data.status}`}>
            {data.status === "running" ? "处理中" : data.status === "error" ? "失败" : "已完成"}
          </span>
        )}
      </div>
      <Handle className="canvas-handle" type="source" position={Position.Right} />
      <div className="canvas-quick-add-wrap" ref={quickAddWrapRef}>
        <button
          className="canvas-quick-add"
          type="button"
          aria-label="添加后续节点"
          title="添加后续节点"
          onClick={(event) => {
            event.stopPropagation();
            setQuickAddOpen((current) => !current);
          }}
        >
          ＋
        </button>
        {quickAddOpen && (
          <div className="canvas-quick-add-menu" onPointerDown={(event) => event.stopPropagation()}>
            <span>添加后续节点</span>
            {(Object.keys(NODE_META) as CanvasNodeKind[]).map((kind) => (
              <button
                key={kind}
                type="button"
                onClick={() => {
                  data.onQuickAdd?.(id, kind);
                  setQuickAddOpen(false);
                }}
              >
                <i className={`canvas-quick-add-icon ${NODE_META[kind].className}`}>{NODE_META[kind].icon}</i>
                {NODE_META[kind].label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function TextNode(props: NodeProps<CanvasNode>) {
  const { data, id } = props;
  return (
    <NodeShell {...props}>
      <textarea
        className="canvas-textarea"
        value={data.config.content || ""}
        onChange={(event) => data.onChange?.(id, { content: event.target.value })}
        placeholder="输入提示词、脚本或创意..."
        onPointerDown={(event) => event.stopPropagation()}
      />
      <div className="canvas-node-row">
        <span className="canvas-field-label">模型</span>
        <select
          value={data.config.model || data.models?.[0]?.id || ""}
          onChange={(event) => data.onChange?.(id, { model: event.target.value })}
          onPointerDown={(event) => event.stopPropagation()}
        >
          {data.models?.length ? (
            data.models.map((model) => (
              <option key={model.id} value={model.id}>{model.name}</option>
            ))
          ) : (
            <option value="">自动选择</option>
          )}
        </select>
        <button
          className="canvas-polish"
          type="button"
          title="使用选中的模型润化文本"
          onClick={() => data.onPolish?.(id)}
        >
          ✦ AI润化
        </button>
      </div>
    </NodeShell>
  );
}

function formatFrameTime(time: number) {
  const minutes = Math.floor(time / 60);
  const seconds = time % 60;
  return `${String(minutes).padStart(2, "0")}:${seconds.toFixed(1).padStart(4, "0")}`;
}

function waitForVideoEvent(video: HTMLVideoElement, eventName: "loadedmetadata" | "seeked") {
  return new Promise<void>((resolve, reject) => {
    const done = () => {
      cleanup();
      resolve();
    };
    const failed = () => {
      cleanup();
      reject(new Error("视频帧读取失败"));
    };
    const cleanup = () => {
      video.removeEventListener(eventName, done);
      video.removeEventListener("error", failed);
    };
    video.addEventListener(eventName, done, { once: true });
    video.addEventListener("error", failed, { once: true });
  });
}

async function loadFrameVideo(url: string) {
  const video = document.createElement("video");
  video.muted = true;
  video.playsInline = true;
  video.preload = "auto";
  video.src = url;
  if (video.readyState < HTMLMediaElement.HAVE_METADATA) {
    await waitForVideoEvent(video, "loadedmetadata");
  }
  return video;
}

async function captureVideoFrame(video: HTMLVideoElement, time: number, maxEdge: number) {
  const safeTime = Math.min(Math.max(time, 0.001), Math.max(video.duration - 0.001, 0.001));
  if (Math.abs(video.currentTime - safeTime) > 0.0001) {
    video.currentTime = safeTime;
    await waitForVideoEvent(video, "seeked");
  }
  const scale = Math.min(1, maxEdge / Math.max(video.videoWidth || maxEdge, video.videoHeight || maxEdge));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round((video.videoWidth || maxEdge) * scale));
  canvas.height = Math.max(1, Math.round((video.videoHeight || maxEdge) * scale));
  canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("无法生成视频帧图片"))), "image/jpeg", 0.9);
  });
}

function VideoFramePreview({
  videoUrl,
  onFrameImage,
}: {
  videoUrl: string;
  onFrameImage: (time: number) => void;
}) {
  const [mode, setMode] = useState<"frame" | "15s" | "30s" | "custom">("frame");
  const [customSeconds, setCustomSeconds] = useState("5");
  const [frames, setFrames] = useState<FramePreview[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [total, setTotal] = useState(0);

  const interval = mode === "frame"
    ? 1 / PREVIEW_FRAME_RATE
    : mode === "15s"
      ? 15
      : mode === "30s"
        ? 30
        : Math.max(Number(customSeconds) || 1, 0.1);

  useEffect(() => {
    let cancelled = false;
    const urls: string[] = [];
    setFrames([]);
    setState("loading");
    setTotal(0);
    const createFrames = async () => {
      try {
        const video = await loadFrameVideo(videoUrl);
        if (!Number.isFinite(video.duration) || video.duration <= 0) throw new Error("视频时长无效");
        const times: number[] = [];
        for (let time = 0; time < video.duration; time += interval) times.push(time);
        if (!times.length) times.push(0);
        setTotal(times.length);
        const previewTimes = times.slice(0, MAX_FRAME_PREVIEWS);
        for (const time of previewTimes) {
          if (cancelled) return;
          const blob = await captureVideoFrame(video, time, 260);
          const url = URL.createObjectURL(blob);
          urls.push(url);
          if (!cancelled) setFrames((current) => [...current, { time, url }]);
        }
        if (!cancelled) setState("ready");
      } catch {
        if (!cancelled) setState("error");
      }
    };
    void createFrames();
    return () => {
      cancelled = true;
      urls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [interval, videoUrl]);

  return (
    <div className="canvas-frame-preview" onPointerDown={(event) => event.stopPropagation()}>
      <div className="canvas-frame-preview-head">
        <span>按帧预览</span>
        <em>{state === "loading" ? "抽帧中…" : state === "error" ? "抽帧失败" : `${frames.length} 张`}</em>
      </div>
      <div className="canvas-frame-options" role="group" aria-label="视频抽帧间隔">
        {([
          ["frame", "每秒"],
          ["15s", "15s"],
          ["30s", "30s"],
          ["custom", "自定义"],
        ] as const).map(([value, label]) => (
          <button key={value} className={mode === value ? "active" : ""} type="button" onClick={() => setMode(value)}>{label}</button>
        ))}
        {mode === "custom" && <label className="canvas-frame-custom"><input type="number" min="0.1" step="0.1" value={customSeconds} onChange={(event) => setCustomSeconds(event.target.value)} />s</label>}
      </div>
      {total > MAX_FRAME_PREVIEWS && <p className="canvas-frame-limit">为保持画布流畅，当前展示前 {MAX_FRAME_PREVIEWS} / {total} 帧。</p>}
      <div
        className="canvas-frame-list nowheel"
        aria-live="polite"
        onWheel={(event) => {
          const list = event.currentTarget;
          if (list.scrollWidth <= list.clientWidth) return;
          const delta = event.deltaY || event.deltaX;
          if (!delta) return;
          event.preventDefault();
          event.stopPropagation();
          list.scrollLeft += delta;
        }}
      >
        {frames.map((frame) => (
          <div className="canvas-frame-item" key={`${frame.time}-${frame.url}`}>
            <img src={frame.url} alt={`${formatFrameTime(frame.time)} 视频帧`} />
            <span>{formatFrameTime(frame.time)}</span>
            <button type="button" title="以这一帧创建图片上传节点" onClick={() => onFrameImage(frame.time)}>＋图片</button>
          </div>
        ))}
      </div>
    </div>
  );
}

function UploadNode(props: NodeProps<CanvasNode>) {
  const { data, id } = props;
  const isVideo = data.kind === "video-upload";
  const mediaUrl = data.config.fileUrl || data.previewUrl;
  const clearFile = () => data.onChange?.(id, {
    fileName: "",
    filePath: "",
    fileUrl: "",
    contentType: "",
    size: "",
  });
  const fileInput = (
    <input
      type="file"
      accept={isVideo ? "video/*" : "image/*"}
      onChange={(event) => {
        const file = event.target.files?.[0];
        if (file) data.onUpload?.(id, file);
        event.currentTarget.value = "";
      }}
    />
  );
  return (
    <NodeShell {...props}>
      {mediaUrl ? (
        <>
          <div className={`canvas-media-preview ${isVideo ? "video" : "image"}`} onPointerDown={(event) => event.stopPropagation()}>
            {isVideo ? (
              <video src={mediaUrl} controls preload="metadata" />
            ) : (
              <img src={mediaUrl} alt={data.config.fileName || "已上传图片"} />
            )}
            {!isVideo && (
              <div className="canvas-media-overlay">
                <label className="canvas-media-action">换图{fileInput}</label>
                <button className="canvas-media-action danger" type="button" onClick={clearFile}>删除</button>
              </div>
            )}
          </div>
          {isVideo && (
            <>
              <div className="canvas-media-actions" onPointerDown={(event) => event.stopPropagation()}>
                <label className="canvas-media-action">换文件{fileInput}</label>
                <button className="canvas-media-action danger" type="button" onClick={clearFile}>删除</button>
              </div>
              {data.config.fileUrl && <VideoFramePreview videoUrl={data.config.fileUrl} onFrameImage={(time) => data.onFrameImage?.(id, time)} />}
            </>
          )}
          <div className="canvas-file-name" title={data.config.fileName}>{data.config.fileName}</div>
        </>
      ) : (
        <label className="canvas-upload-box" onPointerDown={(event) => event.stopPropagation()}>
          {fileInput}
          <span className="canvas-upload-symbol">{isVideo ? "▶" : "▧"}</span>
          <strong>点击上传{isVideo ? "视频" : "图片"}</strong>
          <small>{isVideo ? "MP4 / WebM / MOV" : "JPG / PNG / WebP"}</small>
        </label>
      )}
    </NodeShell>
  );
}

function ImagePreviewDialog({ url, name, onClose }: { url: string; name: string; onClose: () => void }) {
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return createPortal(
    <div
      className="canvas-image-lightbox"
      role="dialog"
      aria-modal="true"
      aria-label={`${name} 放大预览`}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="canvas-image-lightbox-content">
        <img src={url} alt={name} />
        <button type="button" aria-label="关闭预览" onClick={onClose}>×</button>
      </div>
    </div>,
    document.body,
  );
}

function AiImageNode(props: NodeProps<CanvasNode>) {
  const { data, id } = props;
  const [previewOpen, setPreviewOpen] = useState(false);
  const imageModels = data.models?.filter((model) => model.supports_image_generation);
  const modelOptions = imageModels?.length ? imageModels : data.models || [];
  return (
    <NodeShell {...props}>
      <textarea
        className="canvas-textarea canvas-prompt"
        value={data.config.prompt || ""}
        onChange={(event) => data.onChange?.(id, { prompt: event.target.value })}
        placeholder="描述你想生成的图片内容..."
        onPointerDown={(event) => event.stopPropagation()}
      />
      <div className="canvas-config-grid">
        <label><span>比例</span><select value={data.config.ratio} onChange={(event) => data.onChange?.(id, { ratio: event.target.value })} onPointerDown={(event) => event.stopPropagation()}><option>1:1</option><option>4:3</option><option>3:4</option><option>16:9</option><option>9:16</option></select></label>
        <label><span>模型</span><select value={data.config.model || modelOptions[0]?.id || ""} onChange={(event) => data.onChange?.(id, { model: event.target.value })} onPointerDown={(event) => event.stopPropagation()}>
          {modelOptions.length ? modelOptions.map((model) => <option key={model.id} value={model.id}>{model.name}</option>) : <option value="">自动选择图片模型</option>}
        </select></label>
      </div>
      <button className="canvas-generate" type="button" disabled={data.status === "running"} onClick={() => data.onGenerate?.(id)}>{data.status === "running" ? "生成中…" : "生成图片"}</button>
      {data.config.outputUrl && <div className="canvas-generated-output">
        <button className="canvas-generated-image" type="button" onPointerDown={(event) => event.stopPropagation()} onClick={() => setPreviewOpen(true)} title="点击放大查看">
          <img src={data.config.outputUrl} alt={data.config.outputFileName || "生成图片"} />
          <span>点击放大</span>
        </button>
        <div className="canvas-generated-actions"><span>最新产出</span><a href={data.config.outputUrl} download={data.config.outputFileName || "generated-image.png"}>下载图片</a></div>
      </div>}
      {previewOpen && data.config.outputUrl && <ImagePreviewDialog url={data.config.outputUrl} name={data.config.outputFileName || "生成图片"} onClose={() => setPreviewOpen(false)} />}
    </NodeShell>
  );
}

function AiVideoNode(props: NodeProps<CanvasNode>) {
  const { data, id } = props;
  const videoModels = data.models?.filter((model) => model.supports_video_generation);
  const modelOptions = videoModels?.length ? videoModels : data.models || [];
  const set = (key: string, value: string) => data.onChange?.(id, { [key]: value });
  return (
    <NodeShell {...props}>
      <textarea className="canvas-textarea canvas-prompt" value={data.config.prompt || ""} onChange={(event) => set("prompt", event.target.value)} placeholder="描述你想生成的视频内容..." onPointerDown={(event) => event.stopPropagation()} />
      <div className="canvas-config-grid">
        <label><span>比例</span><select value={data.config.ratio} onChange={(event) => set("ratio", event.target.value)} onPointerDown={(event) => event.stopPropagation()}><option>16:9</option><option>9:16</option><option>4:3</option><option>3:4</option><option>1:1</option></select></label>
        <label><span>模型</span><select value={data.config.model || modelOptions[0]?.id || ""} onChange={(event) => set("model", event.target.value)} onPointerDown={(event) => event.stopPropagation()}>{modelOptions.length ? modelOptions.map((model) => <option key={model.id} value={model.id}>{model.name}</option>) : <option value="">自动选择视频模型</option>}</select></label>
        <label><span>时长</span><select value={data.config.duration} onChange={(event) => set("duration", event.target.value)} onPointerDown={(event) => event.stopPropagation()}><option>5s</option><option>10s</option><option>15s</option></select></label>
        <label><span>清晰度</span><select value={data.config.resolution} onChange={(event) => set("resolution", event.target.value)} onPointerDown={(event) => event.stopPropagation()}><option>1080p</option><option>720p</option><option>4K</option></select></label>
      </div>
      <div className="canvas-audio-toggle"><button className={data.config.audio === "有声" ? "active" : ""} type="button" onClick={() => set("audio", "有声")}>◉ 有声</button><button className={data.config.audio === "无声" ? "active" : ""} type="button" onClick={() => set("audio", "无声")}>◌ 无声</button></div>
      <button className="canvas-generate" type="button" disabled={data.status === "running"} onClick={() => data.onGenerate?.(id)}>{data.status === "running" ? "生成中…" : "生成视频"}</button>
      {data.config.outputUrl && <div className="canvas-generated-output video">
        <video src={data.config.outputUrl} controls preload="metadata" />
        <div className="canvas-generated-actions"><span>最新产出</span><a href={data.config.outputUrl} download={data.config.outputFileName || "generated-video.mp4"}>下载视频</a></div>
      </div>}
    </NodeShell>
  );
}

function NoteNode(props: NodeProps<CanvasNode>) {
  const { data, id } = props;
  return <NodeShell {...props}><textarea className="canvas-textarea canvas-note-text" value={data.config.content || ""} onChange={(event) => data.onChange?.(id, { content: event.target.value })} placeholder="记录想法、说明或待办..." onPointerDown={(event) => event.stopPropagation()} /></NodeShell>;
}

const nodeTypes = {
  text: TextNode,
  "image-upload": UploadNode,
  "ai-image": AiImageNode,
  "video-upload": UploadNode,
  "ai-video": AiVideoNode,
  note: NoteNode,
};

const EMPTY_GRAPH: CanvasGraph = { nodes: [], edges: [], viewport: { x: 0, y: 0, zoom: 1 } };
const GRID_SIZE = 24;

function workspaceFileUrl(workspaceId: string, path: string) {
  return `/api/workspaces/${encodeURIComponent(workspaceId)}/files/${path
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/")}`;
}

type CanvasPageProps = {
  workspaceId: string;
  projectId?: string;
  onProjectSelected?: (id: string) => void;
  onProjectsChange?: (projects: CanvasProject[]) => void;
};

function CanvasEditor({
  workspaceId,
  projectId: requestedProjectId = "",
  onProjectSelected,
  onProjectsChange,
}: CanvasPageProps) {
  const [projects, setProjects] = useState<CanvasProject[]>([]);
  const [projectId, setProjectId] = useState("");
  const [projectName, setProjectName] = useState("未命名项目");
  const [models, setModels] = useState<Model[]>([]);
  const [snapToGrid, setSnapToGrid] = useState(true);
  const [showGrid, setShowGrid] = useState(true);
  const [nodes, setNodes, onNodesChange] = useNodesState<CanvasNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<CanvasEdge>([]);
  const [viewport, setViewport] = useState<Viewport>(EMPTY_GRAPH.viewport);
  const [saveState, setSaveState] = useState<"saved" | "dirty" | "saving" | "error">("saved");
  const [error, setError] = useState("");
  const [flow, setFlow] = useState<ReactFlowInstance<CanvasNode, CanvasEdge> | null>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const loadedRef = useRef(false);
  const savingRef = useRef(false);
  const nodesRef = useRef<CanvasNode[]>([]);
  const projectsRef = useRef<CanvasProject[]>([]);
  const projectWorkspaceRef = useRef(workspaceId);
  const onProjectsChangeRef = useRef(onProjectsChange);
  const quickAddRef = useRef<(sourceId: string, kind: CanvasNodeKind) => void>(() => undefined);
  const frameImageRef = useRef<(sourceId: string, time: number) => void>(() => undefined);

  useEffect(() => {
    nodesRef.current = nodes;
  }, [nodes]);

  useEffect(() => {
    onProjectsChangeRef.current = onProjectsChange;
  }, [onProjectsChange]);

  useEffect(() => {
    json<Model[]>("/api/models")
      .then(setModels)
      .catch(() => setModels([]));
  }, []);

  const actions = useMemo(() => ({
    models,
    onQuickAdd: (sourceId: string, kind: CanvasNodeKind) => quickAddRef.current(sourceId, kind),
    onFrameImage: (sourceId: string, time: number) => frameImageRef.current(sourceId, time),
    onChange: (id: string, patch: Record<string, string>) => {
      setNodes((current) => current.map((node) => node.id === id ? { ...node, data: { ...node.data, config: { ...node.data.config, ...patch } } } : node));
      setSaveState("dirty");
    },
    onRemove: (id: string) => {
      setNodes((current) => current.filter((node) => node.id !== id));
      setEdges((current) => current.filter((edge) => edge.source !== id && edge.target !== id));
      setSaveState("dirty");
    },
    onUpload: async (id: string, file: File) => {
      const projectWorkspaceId = projectWorkspaceRef.current;
      if (!projectWorkspaceId) return;
      setNodes((current) => current.map((node) => node.id === id ? { ...node, data: { ...node.data, status: "running", config: { ...node.data.config, fileName: file.name, contentType: file.type } } } : node));
      const form = new FormData();
      form.append("files", file, file.name);
      try {
        const response = await fetch(`/api/workspaces/${encodeURIComponent(projectWorkspaceId)}/files`, { method: "POST", body: form });
        if (!response.ok) throw new Error(await response.text());
        const data = (await response.json()) as { files: Array<{ path: string; name: string; size: number; content_type: string }> };
        const uploaded = data.files[0];
        setNodes((current) => current.map((node) => node.id === id ? { ...node, data: { ...node.data, previewUrl: undefined, status: "idle", config: { ...node.data.config, fileName: uploaded.name, filePath: uploaded.path, fileUrl: workspaceFileUrl(projectWorkspaceId, uploaded.path), size: String(uploaded.size), contentType: uploaded.content_type } } } : node));
        setSaveState("dirty");
      } catch (reason) {
        setError(`上传素材失败：${String(reason).replace(/^Error:\s*/, "")}`);
        setNodes((current) => current.map((node) => node.id === id ? { ...node, data: { ...node.data, status: "error" } } : node));
        setSaveState("dirty");
      }
    },
    onGenerate: async (id: string) => {
      const projectWorkspaceId = projectWorkspaceRef.current;
      const node = nodesRef.current.find((item) => item.id === id);
      if (!node || !["ai-image", "ai-video"].includes(node.data.kind)) return;
      const prompt = node.data.config.prompt?.trim() || "";
      if (!prompt) {
        setError("请先输入生成提示词");
        return;
      }
      setError("");
      setNodes((current) => current.map((item) => item.id === id ? { ...item, data: { ...item.data, status: "running" } } : item));
      try {
        const result = await json<{ artifact_path: string; content_type: string; model_id: string; project?: CanvasProject }>(`/api/canvas/projects/${encodeURIComponent(projectId || "")}/nodes/${encodeURIComponent(id)}/generate`, {
          method: "POST",
          body: JSON.stringify({
            prompt,
            model_id: node.data.config.model || "",
            ratio: node.data.config.ratio || (node.data.kind === "ai-image" ? "1:1" : "16:9"),
            duration: node.data.config.duration || "5s",
            resolution: node.data.config.resolution || "1080p",
            audio: node.data.config.audio || "有声",
          }),
        });
        const nextConfig = {
          ...node.data.config,
          outputPath: result.artifact_path,
          outputUrl: workspaceFileUrl(projectWorkspaceId, result.artifact_path),
          outputFileName: result.artifact_path.split("/").pop() || "generated-media",
          outputContentType: result.content_type,
          model: result.model_id || node.data.config.model || "",
        };
        setNodes((current) => current.map((item) => item.id === id ? { ...item, data: { ...item.data, status: "success", config: nextConfig } } : item));
        if (result.project) {
          const nextProjects = projectsRef.current.map((project) => project.id === result.project?.id ? result.project : project);
          projectsRef.current = nextProjects;
          setProjects(nextProjects);
          onProjectsChangeRef.current?.(nextProjects);
        }
        setSaveState("saved");
      } catch (reason) {
        setError(`生成失败：${String(reason).replace(/^Error:\s*/, "")}`);
        setNodes((current) => current.map((item) => item.id === id ? { ...item, data: { ...item.data, status: "error" } } : item));
      }
    },
    onPolish: async (id: string) => {
      const node = nodesRef.current.find((item) => item.id === id);
      const content = node?.data.config.content?.trim() || "";
      if (!content) {
        setError("请先输入需要润化的文字");
        return;
      }
      setNodes((current) => current.map((item) => item.id === id ? { ...item, data: { ...item.data, status: "running" } } : item));
      try {
        const result = await json<{ content: string }>("/api/canvas/polish", {
          method: "POST",
          body: JSON.stringify({ model_id: node?.data.config.model || models[0]?.id || "", content }),
        });
        setNodes((current) => current.map((item) => item.id === id ? { ...item, data: { ...item.data, status: "idle", config: { ...item.data.config, content: result.content } } } : item));
        setSaveState("dirty");
      } catch (reason) {
        setError(`AI 润化失败：${String(reason).replace(/^Error:\s*/, "")}`);
        setNodes((current) => current.map((item) => item.id === id ? { ...item, data: { ...item.data, status: "error" } } : item));
      }
    },
  }), [models, projectId, setEdges, setNodes]);

  quickAddRef.current = (sourceId, kind) => {
    const source = nodesRef.current.find((item) => item.id === sourceId);
    if (!source) return;
    const nextNode = makeNode(
      kind,
      { x: source.position.x + 380, y: source.position.y },
      actions,
    );
    setNodes((current) => [...current, nextNode]);
    setEdges((current) => [
      ...current,
      {
        id: `edge-${sourceId}-${nextNode.id}`,
        source: sourceId,
        target: nextNode.id,
        type: "default",
        animated: true,
        markerEnd: { type: MarkerType.ArrowClosed, color: "#c9a99d" },
      },
    ]);
    setSaveState("dirty");
  };

  frameImageRef.current = (sourceId, time) => {
    const source = nodesRef.current.find((item) => item.id === sourceId);
    if (!source?.data.config.fileUrl) return;
    const createImageNode = async () => {
      try {
        const video = await loadFrameVideo(source.data.config.fileUrl);
        const blob = await captureVideoFrame(video, time, 2048);
        const sourceName = source.data.config.fileName.replace(/\.[^/.]+$/, "") || "video-frame";
        const frameName = `${sourceName}-${Math.round(time * 1000)}ms.jpg`;
        const previewUrl = URL.createObjectURL(blob);
        const nextNode = makeNode("image-upload", { x: source.position.x + 380, y: source.position.y + 42 }, actions);
        nextNode.data = {
          ...nextNode.data,
          previewUrl,
          status: "running",
          config: { ...nextNode.data.config, fileName: frameName, contentType: "image/jpeg" },
        };
        setNodes((current) => [...current, nextNode]);
        setEdges((current) => [
          ...current,
          {
            id: `edge-${sourceId}-${nextNode.id}`,
            source: sourceId,
            target: nextNode.id,
            type: "default",
            animated: true,
            markerEnd: { type: MarkerType.ArrowClosed, color: "#c9a99d" },
          },
        ]);
        setSaveState("dirty");
        void actions.onUpload?.(nextNode.id, new File([blob], frameName, { type: "image/jpeg" }));
      } catch (reason) {
        setError(`创建图片节点失败：${String(reason).replace(/^Error:\s*/, "")}`);
      }
    };
    void createImageNode();
  };

  const hydrate = useCallback((graph: CanvasGraph, projectWorkspaceId: string) => {
    const hydrated = (graph.nodes || []).map((item) => {
      const config = {
        ...DEFAULT_CONFIG[item.type],
        ...((item.data.config || {}) as Record<string, string>),
      };
      if (!config.scope) config.scope = "direct";
      if (config.filePath && !config.fileUrl) {
        config.fileUrl = workspaceFileUrl(projectWorkspaceId, config.filePath);
      }
      if (config.outputPath && !config.outputUrl) {
        config.outputUrl = workspaceFileUrl(projectWorkspaceId, config.outputPath);
      }
      return {
        ...item,
        type: item.type,
        data: {
          ...item.data,
          title: String(item.data.title || NODE_META[item.type].label),
          kind: item.type,
          config,
          ...actions,
        },
      };
    }) as CanvasNode[];
    setNodes(hydrated);
    setEdges(
      (graph.edges || []).map((edge) => ({
        ...edge,
        type: "default",
        animated: true,
        markerEnd: { type: MarkerType.ArrowClosed, color: "#c9a99d" },
      })) as CanvasEdge[],
    );
    setViewport(graph.viewport || EMPTY_GRAPH.viewport);
  }, [actions, setEdges, setNodes]);

  const loadProjects = useCallback(async () => {
    if (!workspaceId) return;
    loadedRef.current = false;
    try {
      const list = await json<CanvasProject[]>("/api/canvas/projects");
      let available = list;
      if (!available.length) {
        const created = await json<CanvasProject>("/api/canvas/projects/initial", { method: "POST", body: JSON.stringify({ workspace_id: workspaceId, name: "未命名项目", graph: EMPTY_GRAPH }) });
        available = [created];
      }
      setProjects(available);
      projectsRef.current = available;
      onProjectsChange?.(available);
      const current = available.find((item) => item.id === requestedProjectId) || available[0];
      projectWorkspaceRef.current = current.workspace_id;
      setProjectId(current.id);
      onProjectSelected?.(current.id);
      setProjectName(current.name);
      hydrate(current.graph, current.workspace_id);
      setSaveState("saved");
      loadedRef.current = true;
    } catch (reason) {
      setError(`读取画布失败：${String(reason).replace(/^Error:\s*/, "")}`);
    }
  }, [hydrate, onProjectSelected, requestedProjectId, workspaceId]);

  useEffect(() => { void loadProjects(); }, [loadProjects]);
  useEffect(() => {
    if (flow && projectId) void flow.setViewport(viewport);
  }, [flow, projectId]);

  const graph = useCallback((): CanvasGraph => ({ nodes: nodes.map(nodeToPersisted), edges: edges as Array<Record<string, unknown>>, viewport }), [edges, nodes, viewport]);
  const save = useCallback(async () => {
    if (!projectId || !loadedRef.current || savingRef.current) return;
    savingRef.current = true;
    setSaveState("saving");
    try {
      const updated = await json<CanvasProject>(`/api/canvas/projects/${encodeURIComponent(projectId)}`, { method: "PATCH", body: JSON.stringify({ name: projectName.trim() || "未命名项目", graph: graph() }) });
      const nextProjects = projects.map((project) => project.id === updated.id ? updated : project);
      setProjects(nextProjects);
      onProjectsChange?.(nextProjects);
      setSaveState("saved");
    } catch (reason) {
      setError(`保存画布失败：${String(reason).replace(/^Error:\s*/, "")}`);
      setSaveState("error");
    } finally { savingRef.current = false; }
  }, [graph, onProjectsChange, projectId, projectName, projects]);

  useEffect(() => {
    if (saveState !== "dirty" || !loadedRef.current) return;
    const timer = window.setTimeout(() => void save(), 900);
    return () => window.clearTimeout(timer);
  }, [save, saveState]);

  const updateNodes = (changes: NodeChange<CanvasNode>[]) => { onNodesChange(changes); if (changes.length) setSaveState("dirty"); };
  const updateEdges = (changes: EdgeChange<CanvasEdge>[]) => { onEdgesChange(changes); if (changes.length) setSaveState("dirty"); };
  const onConnect = (connection: Connection) => {
    if (!connection.source || !connection.target || isCycle(edges, connection)) return;
    if (edges.some((edge) => edge.source === connection.source && edge.target === connection.target)) return;
    setEdges((current) =>
      addEdge(
        {
          ...connection,
          type: "default",
          animated: true,
          markerEnd: { type: MarkerType.ArrowClosed, color: "#c9a99d" },
        },
        current,
      ),
    );
    setSaveState("dirty");
  };
  const addNode = (kind: CanvasNodeKind, position?: { x: number; y: number }) => {
    const bounds = canvasRef.current?.getBoundingClientRect();
    const target = position || (flow && bounds ? flow.screenToFlowPosition({ x: bounds.left + bounds.width / 2, y: bounds.top + bounds.height / 2 }) : { x: 120, y: 120 });
    setNodes((current) => [...current, makeNode(kind, target, actions)]);
    setSaveState("dirty");
  };
  const selectProject = (id: string) => {
    const next = projects.find((item) => item.id === id);
    if (!next) return;
    projectWorkspaceRef.current = next.workspace_id;
    setProjectId(next.id); onProjectSelected?.(next.id); setProjectName(next.name); hydrate(next.graph, next.workspace_id); setSaveState("saved");
  };
  const createProject = async () => {
    try {
      const endpoint = projects.length ? "/api/canvas/projects" : "/api/canvas/projects/initial";
      const created = await json<CanvasProject>(endpoint, { method: "POST", body: JSON.stringify({ workspace_id: workspaceId, name: "未命名项目", graph: EMPTY_GRAPH }) });
      const nextProjects = [created, ...projects];
      setProjects(nextProjects);
      onProjectsChange?.(nextProjects);
      onProjectSelected?.(created.id);
      setProjectId(created.id);
      setProjectName(created.name);
      projectWorkspaceRef.current = created.workspace_id;
      hydrate(created.graph, created.workspace_id);
      setSaveState("saved");
    } catch (reason) { setError(`新建画布失败：${String(reason).replace(/^Error:\s*/, "")}`); }
  };
  const onDrop = (event: React.DragEvent) => {
    event.preventDefault();
    const kind = event.dataTransfer.getData("application/x-canvas-node") as CanvasNodeKind;
    if (!kind || !flow) return;
    addNode(kind, flow.screenToFlowPosition({ x: event.clientX, y: event.clientY }));
  };

  return (
    <section className="canvas-page">
      <header className="canvas-topbar">
        <div className="canvas-project-title">
          <span className="eyebrow">WORKFLOW CANVAS</span>
          <div className="canvas-title-row">
            <select value={projectId} onChange={(event) => selectProject(event.target.value)} aria-label="选择画布项目">
              {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
            </select>
            <input value={projectName} onChange={(event) => { setProjectName(event.target.value); setSaveState("dirty"); }} aria-label="画布项目名称" />
          </div>
        </div>
        <div className="canvas-top-actions">
          <span className={`canvas-save-state ${saveState}`}><i />{saveState === "saved" ? "已保存" : saveState === "saving" ? "保存中" : saveState === "error" ? "保存失败" : "未保存"}</span>
          <button className="secondary-button" type="button" onClick={() => void createProject()}>＋ 新建画布</button>
          <button className="primary-button" type="button" onClick={() => void save()} disabled={saveState === "saving"}>保存</button>
        </div>
      </header>
      {error && <div className="canvas-error">{error}<button type="button" onClick={() => setError("")}>×</button></div>}
      <div className="canvas-workspace">
        <aside className="canvas-sidebar">
          <div className="canvas-sidebar-head"><div className="canvas-brand-mark">⌘</div><div><strong>无限画布</strong><span>AI WORKFLOW BUILDER</span></div></div>
          <div className="canvas-sidebar-section"><span className="eyebrow">节点</span>{(Object.keys(NODE_META) as CanvasNodeKind[]).map((kind) => { const item = NODE_META[kind]; return <button key={kind} className={`canvas-palette-item ${item.className}`} type="button" draggable onDragStart={(event) => event.dataTransfer.setData("application/x-canvas-node", kind)} onClick={() => addNode(kind)}><span className="canvas-palette-icon">{item.icon}</span><span><strong>{item.label}</strong><small>{item.description}</small></span><b>⠿</b></button>; })}</div>
          <div className="canvas-sidebar-section canvas-options"><span className="eyebrow">画布</span><label><span>吸附网格</span><input type="checkbox" checked={snapToGrid} onChange={(event) => setSnapToGrid(event.target.checked)} /></label><label><span>显示网格</span><input type="checkbox" checked={showGrid} onChange={(event) => setShowGrid(event.target.checked)} /></label></div>
          <div className="canvas-sidebar-section canvas-stats"><span className="eyebrow">当前项目</span><div><span>节点</span><b>{nodes.length}</b></div><div><span>连线</span><b>{edges.length}</b></div><div><span>状态</span><b>{saveState === "saved" ? "已保存" : "编辑中"}</b></div></div>
        </aside>
        <div className="canvas-stage" ref={canvasRef} onDrop={onDrop} onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }}>
          <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onInit={setFlow} onNodesChange={updateNodes} onEdgesChange={updateEdges} onConnect={onConnect} onMoveEnd={(_, nextViewport) => { setViewport(nextViewport); setSaveState("dirty"); }} fitView defaultViewport={viewport} deleteKeyCode={["Backspace", "Delete"]} selectionOnDrag panOnScroll snapToGrid={snapToGrid} snapGrid={[GRID_SIZE, GRID_SIZE]} connectionLineType={ConnectionLineType.Bezier} defaultEdgeOptions={{ type: "default", animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: "#c9a99d" } }} minZoom={0.25} maxZoom={1.8} proOptions={{ hideAttribution: true }}>
            {showGrid && <Background variant={BackgroundVariant.Lines} color="#ded8cf" bgColor="#fbfaf7" gap={GRID_SIZE} lineWidth={1} />}
            <Controls showInteractive={false} />
            <MiniMap nodeColor={(node) => node.type === "ai-image" || node.type === "ai-video" ? "#e85d45" : "#b8a99b"} maskColor="rgba(247,246,242,.72)" />
          </ReactFlow>
          {!nodes.length && <div className="canvas-empty-hint"><div>✦</div><strong>从左侧添加第一个节点</strong><span>拖拽节点到画布，开始搭建你的 AIGC 工作流</span></div>}
        </div>
      </div>
    </section>
  );
}

export function CanvasPage(props: CanvasPageProps) {
  return <ReactFlowProvider><CanvasEditor {...props} /></ReactFlowProvider>;
}
