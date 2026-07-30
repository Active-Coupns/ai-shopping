import logging
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from routers.dashboard import serve_dashboard

router = APIRouter(prefix="/client", tags=["Client Dashboard"])
logger = logging.getLogger("gateway.router.client")

@router.get("/dashboard", response_class=HTMLResponse, summary="Serve Client Dashboard UI")
async def serve_client_dashboard():
    """Serves the dashboard HTML response for clients."""
    return await serve_dashboard()
