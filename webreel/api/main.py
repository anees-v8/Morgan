from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .routes import generate, status, download

app = FastAPI(
    title="WebReel API",
    description="Autonomous AI Website Video Generator API",
    version="1.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(generate.router, prefix="/api", tags=["Generation"])
app.include_router(status.router, prefix="/api", tags=["Status"])
app.include_router(download.router, prefix="/api", tags=["Download"])

# Static web directory
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
ROOT_DIR = Path(__file__).resolve().parent.parent.parent

@app.get("/webreel_mindmap.html")
async def serve_mindmap():
    mindmap_path = ROOT_DIR / "webreel_mindmap.html"
    if mindmap_path.exists():
        return FileResponse(str(mindmap_path))
    return {"error": "Mindmap not found"}

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "WebReel Autonomous Video Engine",
        "version": "1.0.0"
    }

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
if OUTPUT_DIR.exists():
    app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")

# Mount static files at root so /styles.css, /app.js, and index.html are served cleanly
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")



