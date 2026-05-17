"""Pub/Sub publisher with the replay loop."""
import json
import logging
import threading
import time
from typing import List, Dict, Any

from google.cloud import pubsub_v1

from .config import config
from .replay_clock import ReplayClock

logger = logging.getLogger(__name__)


class Publisher:
    def __init__(self, frames: List[Dict[str, Any]]):
        self.frames = frames
        self.frame_index = {f["race_time_s"]: f for f in frames}
        self.start_tick = frames[0]["race_time_s"]
        self.end_tick = frames[-1]["race_time_s"]

        self._publisher = pubsub_v1.PublisherClient()
        self._topic_path = self._publisher.topic_path(
            config.PROJECT_ID, config.PUBSUB_TOPIC
        )

        self.clock = ReplayClock(
            start_tick=self.start_tick,
            end_tick=self.end_tick,
            speed=config.REPLAY_SPEED_MULTIPLIER,
        )

        self.auto_restart = config.AUTO_RESTART_DEFAULT
        self._last_published_tick = self.start_tick - 1
        self._publish_count = 0
        self._error_count = 0
        self._last_error: str = ""
        self._stop_event = threading.Event()
        self._thread: threading.Thread = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            logger.warning("Publisher already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="replay-publisher")
        self._thread.start()
        logger.info(
            "Publisher started. Topic: %s, frames: %d, start_tick: %d, end_tick: %d",
            self._topic_path, len(self.frames), self.start_tick, self.end_tick,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def restart_replay(self) -> None:
        """Reset clock and tick tracking. Replay starts from start_tick."""
        self.clock.restart()
        self._last_published_tick = self.start_tick - 1
        logger.info("Replay restarted")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick_once()
            except Exception as e:
                self._error_count += 1
                self._last_error = f"{type(e).__name__}: {e}"
                logger.exception("Publisher tick failed")
                time.sleep(0.5)

    def _tick_once(self) -> None:
        race_t = self.clock.race_time_s()

        # End-of-race handling
        if race_t >= self.end_tick:
            if self.auto_restart:
                logger.info("End reached, auto-restarting")
                self.restart_replay()
            else:
                # Sleep briefly and re-check; allows status/restart endpoints to act
                time.sleep(0.25)
            return

        if self.clock.is_paused():
            time.sleep(0.05)
            return

        target_tick = int(race_t)
        if target_tick > self._last_published_tick:
            # Publish all ticks from last+1 through target. Handles speed multipliers > 1.
            for t in range(self._last_published_tick + 1, target_tick + 1):
                frame = self.frame_index.get(t)
                if frame is None:
                    continue
                self._publish_frame(frame)
            self._last_published_tick = target_tick

        # Sleep until next tick boundary (adaptive to speed)
        sleep_s = max(0.01, 0.5 / max(1.0, self.clock.speed()))
        time.sleep(sleep_s)

    def _publish_frame(self, frame: Dict[str, Any]) -> None:
        data = json.dumps(frame).encode("utf-8")
        # Don't await the result — fire and forget for throughput. Errors hit the publish callback.
        future = self._publisher.publish(self._topic_path, data)
        future.add_done_callback(self._publish_callback)
        self._publish_count += 1

    def _publish_callback(self, future) -> None:
        try:
            future.result(timeout=10)
        except Exception as e:
            self._error_count += 1
            self._last_error = f"publish: {type(e).__name__}: {e}"
            logger.exception("Publish callback error")

    def status(self) -> Dict[str, Any]:
        return {
            "race_time_s": round(self.clock.race_time_s(), 2),
            "race_duration_s": self.end_tick - self.start_tick,
            "seconds_remaining": round(max(0, self.end_tick - self.clock.race_time_s()), 2),
            "pct_complete": round(
                max(0, min(100, (self.clock.race_time_s() - self.start_tick) /
                           (self.end_tick - self.start_tick) * 100)), 2),
            "last_published_tick": self._last_published_tick,
            "speed_multiplier": self.clock.speed(),
            "paused": self.clock.is_paused(),
            "auto_restart": self.auto_restart,
            "publish_count": self._publish_count,
            "error_count": self._error_count,
            "last_error": self._last_error,
            "topic": self._topic_path,
            "frames_loaded": len(self.frames),
            "start_tick": self.start_tick,
            "end_tick": self.end_tick,
        }