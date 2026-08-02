from __future__ import annotations

from fastapi import APIRouter
from ...core import *

router = APIRouter()


@router.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "database": str(store.path),
        "skills": len(store.all("skills")),
        "experts": len(store.all("experts")),
        "mcp": len(store.all("mcp_servers")),
        "agentscope_live": os.getenv("AGENTSCOPE_LIVE", "0") == "1",
        "agentscope_available": importlib.util.find_spec("agentscope") is not None,
        "python": sys.executable,
    }


@router.post("/api/system/pick-directory")
async def pick_directory() -> dict[str, Any]:
    if sys.platform != "darwin":
        raise HTTPException(501, "当前系统暂时支持 macOS 文件夹选择器")
    try:
        picker_env = os.environ.copy()
        picker_env.update(
            {
                "AppleLanguages": "(zh-Hans-CN)",
                "AppleLocale": "zh_CN",
                "LANG": "zh_CN.UTF-8",
                "LC_ALL": "zh_CN.UTF-8",
            }
        )
        picker_script = """
tell application "Finder"
    activate
    set selectedFolder to choose folder with prompt "选择工作空间文件夹"
end tell
POSIX path of selectedFolder
"""
        result = await asyncio.to_thread(
            subprocess.run,
            ["osascript", "-e", picker_script],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env=picker_env,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "系统文件夹选择器响应超时")
    if result.returncode != 0:
        if "User canceled" in result.stderr:
            return {"cancelled": True, "path": "", "name": ""}
        raise HTTPException(
            500, f"无法打开系统文件夹选择器：{result.stderr.strip() or '未知错误'}"
        )
    selected = Path(result.stdout.strip()).expanduser().resolve()
    if not selected.is_dir():
        raise HTTPException(400, "系统选择器返回的路径不是文件夹")
    return {
        "cancelled": False,
        "path": str(selected),
        "name": selected.name or str(selected),
    }
