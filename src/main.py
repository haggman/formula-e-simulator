"""FastAPI app entrypoint. Loads frames, starts the publisher, exposes control endpoints."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .config import config
from .frame_loader import load_frames
from .publisher import Publisher

from fastapi.responses import HTMLResponse

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
@app.get("/", response_class=HTMLResponse)
def index():
    status = publisher.status() if publisher else {}
    cfg_speed = status.get("speed_multiplier", "—")
    cfg_paused = status.get("paused", "—")
    cfg_auto = status.get("auto_restart", "—")
    cfg_race_time = status.get("race_time_s", "—")
    cfg_pct = status.get("pct_complete", "—")
    cfg_publish_count = status.get("publish_count", "—")

    return f"""<!doctype html>
<html><head>
  <meta charset="utf-8">
  <title>Formula E Simulator</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            max-width: 760px; margin: 2rem auto; padding: 0 1rem; color: #222; }}
    h1 {{ margin-bottom: 0.2rem; }}
    .sub {{ color: #666; margin-top: 0; margin-bottom: 1.5rem; }}
    table {{ border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; }}
    th, td {{ text-align: left; padding: 0.35rem 0.7rem; border-bottom: 1px solid #eee; }}
    th {{ background: #f7f7f7; }}
    code {{ background: #f4f4f4; padding: 0.1rem 0.35rem; border-radius: 3px; }}
    .method {{ display: inline-block; min-width: 3.2rem;
               font-size: 0.78rem; padding: 0.1rem 0.4rem; border-radius: 3px;
               color: #fff; text-align: center; }}
    .get {{ background: #2c7be5; }}
    .post {{ background: #28a745; }}
    .footer {{ color: #888; font-size: 0.85rem; margin-top: 2rem; }}
  </style>
</head><body>
  <h1>Formula E Simulator</h1>
  <p class="sub">Streaming Berlin 2024 R10 race telemetry at 1 Hz to Pub/Sub.</p>

  <h3>Current state</h3>
  <table>
    <tr><th>Race time</th><td>{cfg_race_time}s ({cfg_pct}% complete)</td></tr>
    <tr><th>Speed multiplier</th><td>{cfg_speed}x</td></tr>
    <tr><th>Paused</th><td>{cfg_paused}</td></tr>
    <tr><th>Auto-restart on chequered</th><td>{cfg_auto}</td></tr>
    <tr><th>Frames published</th><td>{cfg_publish_count}</td></tr>
    <tr><th>Pub/Sub topic</th><td><code>{status.get("topic", "—")}</code></td></tr>
  </table>

  <h3>Endpoints</h3>
  <table>
    <tr><th>Method</th><th>Path</th><th>Body</th><th>Purpose</th></tr>
    <tr><td><span class="method get">GET</span></td><td><a href="/status">/status</a></td><td>—</td><td>Live race state + publish stats</td></tr>
    <tr><td><span class="method get">GET</span></td><td><a href="/config">/config</a></td><td>—</td><td>Active settings</td></tr>
    <tr><td><span class="method get">GET</span></td><td><a href="/schema">/schema</a></td><td>—</td><td>Sample frame for agent devs</td></tr>
    <tr><td><span class="method get">GET</span></td><td><a href="/health">/health</a></td><td>—</td><td>Liveness probe</td></tr>
    <tr><td><span class="method get">GET</span></td><td><a href="/docs">/docs</a></td><td>—</td><td>Auto-generated Swagger UI</td></tr>
    <tr><td><span class="method post">POST</span></td><td><code>/restart</code></td><td>—</td><td>Reset replay to t=0</td></tr>
    <tr><td><span class="method post">POST</span></td><td><code>/pause</code></td><td>—</td><td>Freeze the clock</td></tr>
    <tr><td><span class="method post">POST</span></td><td><code>/resume</code></td><td>—</td><td>Resume from pause</td></tr>
    <tr><td><span class="method post">POST</span></td><td><code>/speed</code></td><td><code>{{"multiplier": 2.0}}</code></td><td>Change replay speed live</td></tr>
    <tr><td><span class="method post">POST</span></td><td><code>/jump</code></td><td><code>{{"race_time_s": 1800}}</code></td><td>Seek to a specific race time</td></tr>
    <tr><td><span class="method post">POST</span></td><td><code>/auto-restart</code></td><td><code>{{"enabled": true}}</code></td><td>Toggle loop-on-chequered</td></tr>
  </table>

  <p class="footer">
    Race duration: ~47:48 (2868s). Frames artifact:
    <code>gs://{config.FRAMES_BUCKET}/{config.FRAMES_PATH}</code>
  </p>
</body></html>"""

@app.get("/health")
def health():
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