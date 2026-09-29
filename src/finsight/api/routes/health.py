from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


@router.get("/health")
@router.get("/health/live")
def health() -> dict:
    return {
        "status": "ok",
        "service": "finsight-ai",
        "version": "0.1.0",
    }


@router.get("/health/startup")
def startup(request: Request):
    ready = bool(getattr(request.app.state, "startup_complete", False))
    return JSONResponse({"status": "started" if ready else "starting"},
                        status_code=200 if ready else 503)


@router.get("/health/ready")
def readiness(request: Request):
    checker = getattr(request.app.state, "deployment_readiness", None)
    if not getattr(request.app.state, "startup_complete", False) or checker is None:
        return JSONResponse({"status": "not_ready"}, status_code=503)
    report = checker.report()
    return JSONResponse(report, status_code=200 if report["status"] == "ready" else 503)
