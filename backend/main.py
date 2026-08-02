from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core import ROOT
from .api.routers import (
    canvas,
    capabilities,
    experts,
    messages,
    mcp,
    memory,
    runs,
    skillhub,
    skills,
    system,
    tasks,
    workspaces,
)

app = FastAPI(title="mini-workbuddy API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for _router_module in (
    system,
    canvas,
    workspaces,
    tasks,
    skills,
    experts,
    skillhub,
    mcp,
    memory,
    capabilities,
    runs,
    messages,
):
    app.include_router(_router_module.router)

__all__ = ["app"]
