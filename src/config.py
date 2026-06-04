"""Environment configuration. All values are read once at startup."""
import os


class Config:
    # GCP context
    PROJECT_ID: str = os.environ.get("GOOGLE_CLOUD_PROJECT", "")

    # Pub/Sub
    PUBSUB_TOPIC: str = os.environ.get("PUBSUB_TOPIC", "fe-telemetry")

    # Frames artifact
    FRAMES_BUCKET: str = os.environ.get("FRAMES_BUCKET", "class-demo")
    FRAMES_PATH: str = os.environ.get(
        "FRAMES_PATH", "formula-e/r10/simulator/frames_v3.jsonl.gz"
    )

    # Replay behavior
    REPLAY_SPEED_MULTIPLIER: float = float(
        os.environ.get("REPLAY_SPEED_MULTIPLIER", "1.0")
    )
    AUTO_RESTART_DEFAULT: bool = (
        os.environ.get("AUTO_RESTART", "false").lower() == "true"
    )

    # Race identification
    RACE_ID: str = os.environ.get("RACE_ID", "berlin_2024_r10")

    def __init__(self):
        if not self.PROJECT_ID:
            raise RuntimeError(
                "GOOGLE_CLOUD_PROJECT env var is required. "
                "Set it in Cloud Run or via gcloud config."
            )


config = Config()