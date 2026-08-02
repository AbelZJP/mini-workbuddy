from __future__ import annotations

from fastapi import APIRouter
from ...core import *
from ...services.workspace_service import workspace_row

router = APIRouter()


@router.get("/api/workspaces", response_model=list[Workspace])
async def list_workspaces():
    return [workspace_row(row) for row in store.all("workspaces")]


@router.post("/api/workspaces", response_model=Workspace)
async def create_workspace(payload: CreateWorkspace):
    workspace_id = uuid.uuid4().hex[:10]
    stamp = now()
    root_path = str(Path(payload.root_path).expanduser().resolve())
    root = Path(root_path)
    if not root.exists() or not root.is_dir():
        raise HTTPException(400, "工作空间路径必须是已存在的本机文件夹")
    row = {
        "id": workspace_id,
        "name": payload.name,
        "root_path": root_path,
        "description": payload.description,
        "created_at": stamp,
        "updated_at": stamp,
    }
    store.insert("workspaces", row)
    return workspace_row(row)


@router.patch("/api/workspaces/{workspace_id}", response_model=Workspace)
async def update_workspace(workspace_id: str, payload: CreateWorkspace):
    if not store.one("workspaces", "id=?", (workspace_id,)):
        raise HTTPException(404, "workspace not found")
    root = Path(payload.root_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise HTTPException(400, "工作空间路径必须是已存在的本机文件夹")
    row = store.update(
        "workspaces",
        "id",
        workspace_id,
        {
            "name": payload.name,
            "root_path": str(root),
            "description": payload.description,
            "updated_at": now(),
        },
    )
    return workspace_row(row or {})


@router.post("/api/workspaces/{workspace_id}/files")
async def upload_workspace_files(
    workspace_id: str, files: list[UploadFile] = File(...)
):
    workspace = store.one("workspaces", "id=?", (workspace_id,))
    if not workspace:
        raise HTTPException(404, "工作空间不存在")
    root = Path(workspace["root_path"]).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise HTTPException(400, "工作空间文件夹不存在")
    uploaded: list[dict[str, Any]] = []
    for upload in files:
        raw_name = (upload.filename or "未命名文件").replace("\\", "/")
        parts = [
            part
            for part in Path(raw_name).as_posix().split("/")
            if part not in ("", ".", "..")
        ]
        if not parts:
            parts = ["未命名文件"]
        target = root.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            stem, suffix = target.stem, target.suffix
            index = 1
            while target.exists():
                target = target.with_name(f"{stem} ({index}){suffix}")
                index += 1
        content = await upload.read()
        target.write_bytes(content)
        relative = target.relative_to(root).as_posix()
        uploaded.append(
            {
                "name": target.name,
                "path": relative,
                "size": len(content),
                "content_type": upload.content_type or "application/octet-stream",
            }
        )
    return {"files": uploaded}


@router.post("/api/workspaces/import", response_model=Workspace)
async def import_workspace(request: Request):
    """Import a browser-selected folder into a local workspace.

    Browsers intentionally do not expose the absolute local folder path. The selected
    folder is therefore copied into .mini-workbuddy/imported-workspaces and becomes a
    real local workspace owned by the app.
    """
    content_type = request.headers.get("content-type", "")
    boundary_match = re.search(r"boundary=([^;]+)", content_type)
    if not boundary_match:
        raise HTTPException(400, "需要 multipart/form-data 文件夹上传")
    boundary = ("--" + boundary_match.group(1).strip('"')).encode()
    body = await request.body()
    fields: dict[str, str] = {}
    uploads: list[tuple[str, bytes]] = []
    for part in body.split(boundary):
        if b"Content-Disposition:" not in part:
            continue
        header_end = part.find(b"\r\n\r\n")
        if header_end < 0:
            continue
        headers = part[:header_end].decode("utf-8", errors="ignore")
        payload = part[header_end + 4 :]
        if payload.endswith(b"\r\n"):
            payload = payload[:-2]
        name_match = re.search(r'name="([^"]+)"', headers)
        filename_match = re.search(r'filename="([^"]*)"', headers)
        if filename_match:
            uploads.append((filename_match.group(1), payload))
        elif name_match:
            fields[name_match.group(1)] = payload.decode("utf-8", errors="ignore")
    safe_name = (
        re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", fields.get("name", "")).strip("-")
        or "导入工作空间"
    )
    workspace_id = uuid.uuid4().hex[:10]
    root_path = DATA / "imported-workspaces" / f"{safe_name}-{workspace_id}"
    root_path.mkdir(parents=True, exist_ok=True)
    for filename, content in uploads:
        relative = Path(filename or "untitled").as_posix()
        relative_parts = [
            part for part in relative.split("/") if part not in ("", ".", "..")
        ]
        if not relative_parts:
            continue
        target = root_path.joinpath(*relative_parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    stamp = now()
    row = {
        "id": workspace_id,
        "name": safe_name,
        "root_path": str(root_path),
        "description": "从本机文件夹导入",
        "created_at": stamp,
        "updated_at": stamp,
    }
    store.insert("workspaces", row)
    return workspace_row(row)


@router.delete("/api/workspaces/{workspace_id}")
async def delete_workspace(workspace_id: str):
    if workspace_id == "default":
        raise HTTPException(400, "默认工作空间不能删除")
    if not store.one("workspaces", "id=?", (workspace_id,)):
        raise HTTPException(404, "workspace not found")
    store.delete("workspaces", "id", workspace_id)
    return {"ok": True}
