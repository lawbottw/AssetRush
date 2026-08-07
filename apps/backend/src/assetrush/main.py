from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from assetrush import __version__
from assetrush.routers import health

app = FastAPI(
    title="AssetRush API",
    version=__version__,
    description="遊戲狀態的唯一擁有者。所有規則判定都在 engine/（鐵律 1）。",
)

# M0 只開發期用；正式環境的來源清單在 issue #5 接上環境變數後收斂。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
