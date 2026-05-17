"""FastAPI app entrypoint. Loads frames, starts the publisher, exposes control endpoints."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .config import config
from .frame_loader import load_frames
from .publisher import Publisher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Single shared publisher instance, set on startup
publisher: Publisher = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load frames and start publishing on container startup."""
    global publisher
    logger.info("Project: %s, topic: %s", config.PROJECT_ID, config.PUBSUB_TOPIC)
    frames = load_frames()
    publisher = Publisher(frames)
    publisher.start()
    yield
    logger.info("Shutting down publisher")
    publisher.stop()


app = FastAPI(title="Formula E Race Engineer Simulator", lifespan=lifespan)


# --- Request bodies ---
class SpeedRequest(BaseModel):
    multiplier: float


class JumpRequest(BaseModel):
    race_time_s: float


class AutoRestartRequest(BaseModel):
    enabled: bool


# --- Endpoints ---
@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/status")
def status():
    if publisher is None:
        raise HTTPException(503, "Publisher not initialized")
    return publisher.status()


@app.get("/config")
def get_config():
    if publisher is None:
        raise HTTPException(503, "Publisher not initialized")
    return {
        "speed_multiplier": publisher.clock.speed(),
        "auto_restart": publisher.auto_restart,
        "paused": publisher.clock.is_paused(),
        "project_id": config.PROJECT_ID,
        "topic": config.PUBSUB_TOPIC,
        "frames_bucket": config.FRAMES_BUCKET,
        "frames_path": config.FRAMES_PATH,
        "race_id": config.RACE_ID,
    }


@app.get("/schema")
def schema():
    """Return a representative frame so agent developers know the shape."""
    if publisher is None or not publisher.frames:
        raise HTTPException(503, "Frames not loaded")
    # Use a mid-race frame for the most complete shape (events, AM active, etc.)
    return publisher.frames[len(publisher.frames) // 2]


@app.post("/restart")
def restart():
    if publisher is None:
        raise HTTPException(503, "Publisher not initialized")
    publisher.restart_replay()
    return {"ok": True, "race_time_s": publisher.clock.race_time_s()}


@app.post("/pause")
def pause():
    if publisher is None:
        raise HTTPException(503, "Publisher not initialized")
    publisher.clock.pause()
    return {"ok": True, "paused": True, "race_time_s": publisher.clock.race_time_s()}


@app.post("/resume")
def resume():
    if publisher is None:
        raise HTTPException(503, "Publisher not initialized")
    publisher.clock.resume()
    return {"ok": True, "paused": False, "race_time_s": publisher.clock.race_time_s()}


@app.post("/speed")
def set_speed(req: SpeedRequest):
    if publisher is None:
        raise HTTPException(503, "Publisher not initialized")
    if req.multiplier <= 0:
        raise HTTPException(400, "multiplier must be positive")
    publisher.clock.set_speed(req.multiplier)
    return {"ok": True, "speed_multiplier": publisher.clock.speed()}


@app.post("/jump")
def jump(req: JumpRequest):
    if publisher is None:
        raise HTTPException(503, "Publisher not initialized")
    publisher.clock.jump(req.race_time_s)
    publisher._last_published_tick = int(req.race_time_s) - 1  # republish from new position
    return {"ok": True, "race_time_s": publisher.clock.race_time_s()}


@app.post("/auto-restart")
def set_auto_restart(req: AutoRestartRequest):
    if publisher is None:
        raise HTTPException(503, "Publisher not initialized")
    publisher.auto_restart = req.enabled
    return {"ok": True, "auto_restart": publisher.auto_restart}