from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers.auth import router as auth_router, user_router
from app.routers.db_config import router as db_config_router
from app.routers.comparison import router as comparison_router
from app.routers.snapshot import router as snapshot_router

app = FastAPI(title="Migration Management", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(user_router)
app.include_router(db_config_router)
app.include_router(snapshot_router)
app.include_router(comparison_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
