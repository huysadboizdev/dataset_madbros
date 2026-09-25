from __future__ import annotations

import secrets
import threading
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles

from .api import documents, exports, jobs, results
from .db import Database
from .services.job_service import JobManager
from .settings import Settings, load_settings

MUTATING = {"POST", "PATCH", "PUT", "DELETE"}


def create_app(settings: Optional[Settings] = None, engine: Optional[str] = None,
               engine_extra_args: Optional[List[str]] = None) -> FastAPI:
    import os
    settings = settings or load_settings()
    if engine is None:
        # Fake OCR chi bat khi duoc TEST co nhan gan ro qua env; launcher production khong set.
        engine = os.environ.get("PDFCLEANER_OCR_ENGINE", "paddle")
    db = Database(settings.db_path)
    manager = JobManager(settings, db, engine=engine, engine_extra_args=engine_extra_args)
    interrupted = JobManager.reconcile_on_boot(db)
    # reconcile xong (khong con job RUNNING) -> don dep san pham tam / orphan do lan
    # truoc bi kill giu lai. An toan: chi xoa tmp cua job khong chay va raw orphan
    # khong duoc document nao tham chieu.
    try:
        JobManager.cleanup_orphan_artifacts(db, settings)
    except Exception:
        pass

    @asynccontextmanager
    async def lifespan(app_: FastAPI):
        yield
        manager.shutdown()

    app = FastAPI(title="PDF Cleaner OCR Tool", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db
    app.state.jobs = manager
    app.state.session_token = secrets.token_urlsafe(24)
    app.state.boot_interrupted_jobs = interrupted

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        if request.method in MUTATING:
            origin = request.headers.get("origin")
            if origin:
                host = request.headers.get("host", "")
                if f"http://{host}" != origin.rstrip("/"):
                    return JSONResponse({"detail": "Origin không hợp lệ"}, status_code=403)
            token = request.headers.get("x-pdfcleaner-token", "")
            expected = request.app.state.session_token
            if expected and not secrets.compare_digest(token, expected):
                return JSONResponse({"detail": "Thiếu hoặc sai token phiên. Mở lại ứng dụng."},
                                    status_code=401)
        return await call_next(request)

    @app.get("/api/session")
    def session():
        return {"token": app.state.session_token}

    @app.get("/api/health")
    def health():
        # ocr_ready: kiem model tren DIA (khong import paddle -> nhanh), khong chan
        # toan bo app: neu thieu model, van mo duoc UI de xem ket qua cu / direct extraction.
        # F1: phai la ALL — mot model thieu artifact bat buoc (shard duoc index tham chieu)
        # la 'incomplete' => KHONG duoc coi la san sang OCR (identity mot phan la sai).
        ocr_ready = True
        try:
            from .ocr import model_identity as mi
            root = mi.official_root()
            names = [n for n in (settings.ocr.layout_model_name,
                                 settings.ocr.vl_rec_model_name) if n]
            ocr_ready = bool(root.exists() and names) and all(
                mi.model_fingerprint(n, root).get("status") == "ok" for n in names)
        except Exception:
            ocr_ready = False
        return {
            "app": "ok",
            "version": app.version,
            "db": "ok",
            "engine_mode": engine,
            "ocr_ready": ocr_ready,
            "running_job": bool(db.running_job()),
            "boot_interrupted_jobs": interrupted,
        }

    @app.post("/api/admin/shutdown")
    def shutdown_tool():
        """Stop_Tool.cmd goi: job cho xong trang dang chay duoc trang thai hoa tan
        trong manager.shutdown, worker bi terminate co kiem soat, roi app thoat."""
        import os
        import threading

        def _die():
            manager.shutdown()
            import time
            time.sleep(0.3)
            os._exit(0)

        threading.Thread(target=_die, daemon=True).start()
        return {"ok": True, "message": "Ứng dụng sẽ đóng trong vài giây."}

    app.include_router(documents.router)
    app.include_router(jobs.router)
    app.include_router(results.router)
    app.include_router(exports.router)

    dist = settings.project_root / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            file = (dist / path).resolve()
            if path and file.is_file() and str(file).startswith(str(dist.resolve())):
                return FileResponse(file)
            return FileResponse(dist / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        async def root():
            return {"app": "pdf-cleaner-tool", "ui": "chưa build frontend — chạy npm run build"}

    return app


def run() -> None:
    import uvicorn
    settings = load_settings()
    # Tro toi app module-level de reconcile chi chay mot lan.
    uvicorn.run("backend.app.main:app", host=settings.host, port=settings.port,
                log_level="warning")


# Module-level app cho uvicorn (backend.app.main:app). Khong khoi dong worker/model
# luc import — chi sinh worker khi co job chay.
app = create_app()

if __name__ == "__main__":
    run()
