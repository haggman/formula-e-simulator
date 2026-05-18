# Formula E Race Engineer Simulator

Cloud Run service that replays Berlin 2024 R10 race telemetry at race pace, publishing a unified 1 Hz stream to Pub/Sub. Each team's GCP project gets its own simulator instance, feeding the agent they build in Challenge 2 of the Google Cloud + Formula E hackathon.

## What it does

- Loads a precomputed frames artifact (`frames_v1.jsonl.gz`, ~3 MB, ~2900 frames) from GCS into memory at startup.
- Streams one JSON frame per race-second to the `fe-telemetry` Pub/Sub topic.
- Real race is ~47:48 (2868 seconds). Adjust pace with `REPLAY_SPEED_MULTIPLIER` or the `/speed` endpoint.
- Exposes a browsable HTML index at `/` and control endpoints for pause, resume, restart, jump, speed change, and auto-restart toggle.

## Architecture

```
[GCS frames.jsonl.gz] -> [Cloud Run Service (this)] -> [Pub/Sub fe-telemetry] -> [Agent (Fork 2)]
```

The frames file is built once by the companion notebook (`notebook/build_frames.ipynb`), which reads cleaned R10 data from `gs://class-demo/formula-e/berlin_2024/r10/` and produces a calibrated, physics-informed per-second race timeline. The simulator does no computation — it just plays back.

## Frame schema

Each Pub/Sub message is one frame. See `GET /schema` on a live deploy for an example, or look at any line of `frames_v1.jsonl.gz`. Top-level fields: `schema_version`, `race_id`, `race_time_s`, `race_duration_s`, `pct_complete`, `race_phase`, `current_leader_lap`, `cars[]`, `events[]`. Each car has position, lap, GPS, speed, accel/brake/steer, energy state, attack mode state, and an `is_retired` flag.

## Race timing

The race is **2868 seconds** (~47:48) from green flag to chequered. Frames stream from t=-10 (pre-race grid) to t=~2907 (a few seconds past chequered for cool-down).

After chequered, the simulator either:

- Stops emitting new frames and idles (default), or
- Loops back to t=-10 and replays from the start (if `auto_restart` is on)

Use `POST /restart` to manually rewind anytime.

## Deploy

```bash
chmod +x deploy.sh
./deploy.sh
```

Requires: gcloud CLI authenticated to a project where you have Owner or Editor. The script enables APIs, creates the topic, creates a service account with the right roles, and deploys the service. Idempotent — safe to rerun.

If your project can't read `gs://class-demo` (cross-project), the bucket owner needs to grant `roles/storage.objectViewer` to the service account printed by the script.

After deploy, visit the service URL in a browser for a live status page with clickable endpoint links.

## Endpoints

| Method | Path          | Body                       | Purpose                                |
|--------|---------------|----------------------------|----------------------------------------|
| GET    | /             | —                          | HTML index with live state + endpoints |
| GET    | /health       | —                          | Liveness probe                         |
| GET    | /status       | —                          | Current race time, lap, publish count  |
| GET    | /config       | —                          | Active settings                        |
| GET    | /schema       | —                          | Sample frame for agent devs            |
| GET    | /docs         | —                          | Auto-generated Swagger UI              |
| POST   | /restart      | —                          | Reset to t=0                           |
| POST   | /pause        | —                          | Freeze the clock                       |
| POST   | /resume       | —                          | Resume from pause                      |
| POST   | /speed        | `{"multiplier": 2.0}`      | Change replay speed live               |
| POST   | /jump         | `{"race_time_s": 1800}`    | Seek to a specific race time           |
| POST   | /auto-restart | `{"enabled": true}`        | Toggle loop-on-chequered               |

Note: `/healthz` was renamed to `/health` because Cloud Run's frontend intercepts `/healthz` for its own probes.

## Local development

```bash
pip install -r requirements.txt
export GOOGLE_CLOUD_PROJECT=your-project-id
export FRAMES_BUCKET=class-demo
gcloud auth application-default login
uvicorn src.main:app --reload --port 8080
```

## Environment variables

| Var                       | Default                                          | Notes                              |
|---------------------------|--------------------------------------------------|------------------------------------|
| GOOGLE_CLOUD_PROJECT      | (required)                                       | Cloud Run sets automatically       |
| PUBSUB_TOPIC              | fe-telemetry                                     | Created by deploy.sh               |
| FRAMES_BUCKET             | class-demo                                       | Where frames artifact lives        |
| FRAMES_PATH               | formula-e/r10/simulator/frames_v1.jsonl.gz       | Object name                        |
| REPLAY_SPEED_MULTIPLIER   | 1.0                                              | 1.0 = real-time                    |
| AUTO_RESTART              | false                                            | Loop on chequered                  |
| RACE_ID                   | berlin_2024_r10                                  | Echoed in every frame              |