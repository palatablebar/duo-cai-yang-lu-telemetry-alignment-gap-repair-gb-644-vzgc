"""应用装配：路由注册、健康检查、异常映射。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import config, errors, store
from app.modules.m1_intake import handler as m1
from app.modules.m2_timebase import handler as m2
from app.modules.m3_quality import handler as m3
from app.modules.m4_grid import handler as m4
from app.modules.m5_gaps import handler as m5
from app.modules.m6_batches import handler as m6
from app.modules.m7_export import handler as m7


@asynccontextmanager
async def lifespan(_: FastAPI):
    conn = store.session()
    try:
        store.init_db(conn)
    finally:
        conn.close()
    yield


app = FastAPI(
    title="gridlab 遥测网格",
    version=config.RULE_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

app.add_exception_handler(errors.GridlabError, errors.handle_gridlab_error)

app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")

for module in (m1, m2, m3, m4, m5, m6, m7):
    app.include_router(module.router)


@app.get("/api/health", tags=["ops"])
def health() -> dict:
    return {
        "status": "ok",
        "rule_version": config.RULE_VERSION,
        "grid_minutes": config.GRID_MINUTES,
        "window_minutes": config.WINDOW_MINUTES,
        "max_fill_buckets": config.MAX_FILL_BUCKETS,
    }
