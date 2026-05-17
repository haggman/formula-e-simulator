"""Download and load the precomputed frames JSONL.gz into memory."""
import gzip
import io
import json
import logging
from typing import List, Dict, Any

from google.cloud import storage

from .config import config

logger = logging.getLogger(__name__)


def load_frames() -> List[Dict[str, Any]]:
    """Fetch frames artifact from GCS, decompress, parse JSONL, return list of frames."""
    logger.info(
        "Loading frames from gs://%s/%s",
        config.FRAMES_BUCKET,
        config.FRAMES_PATH,
    )
    client = storage.Client(project=config.PROJECT_ID)
    bucket = client.bucket(config.FRAMES_BUCKET)
    blob = bucket.blob(config.FRAMES_PATH)

    raw = blob.download_as_bytes()
    logger.info("Downloaded %.2f MB compressed", len(raw) / 1e6)

    frames = []
    with gzip.open(io.BytesIO(raw), "rt") as f:
        for line in f:
            frames.append(json.loads(line))

    logger.info(
        "Loaded %d frames (t=%s to t=%s)",
        len(frames),
        frames[0]["race_time_s"],
        frames[-1]["race_time_s"],
    )
    return frames