from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Optional

logger = logging.getLogger("torznabrip.job_store")


class JobState(str, Enum):
    DOWNLOADING = "downloading"
    COMPLETED = "stalledUP"
    FAILED = "error"
    QUEUED = "queuedDL"


@dataclass
class DownloadJob:
    guid: str
    source: str
    release_id: str
    name: str
    save_path: str
    state: JobState = JobState.QUEUED
    progress: float = 0.0
    size: int = 0
    downloaded: int = 0
    error_message: str = ""

    @property
    def hash(self) -> str:
        return hashlib.sha1(self.guid.encode()).hexdigest()

    @property
    def is_finished(self) -> bool:
        return self.state == JobState.COMPLETED

    @property
    def is_failed(self) -> bool:
        return self.state == JobState.FAILED

    def to_dict(self) -> dict:
        d = asdict(self)
        d["state"] = self.state.value
        d["hash"] = self.hash
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "DownloadJob":
        d = dict(d)
        d.pop("hash", None)
        d["state"] = JobState(d.get("state", "queuedDL"))
        return cls(**d)


JOBS_FILE = os.environ.get(
    "JOBS_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs.json"),
)


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, DownloadJob] = {}
        self._loaded = False

    def _save(self) -> None:
        try:
            data = [j.to_dict() for j in self._jobs.values()]
            tmp = JOBS_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, JOBS_FILE)
        except Exception as exc:
            logger.error("Failed to persist jobs: %s", exc)

    def load(self) -> None:
        if not os.path.exists(JOBS_FILE):
            logger.info("No jobs file at %s — starting fresh.", JOBS_FILE)
            self._loaded = True
            return

        try:
            with open(JOBS_FILE) as f:
                data = json.load(f)
            for item in data:
                try:
                    job = DownloadJob.from_dict(item)
                    if job.state in (JobState.DOWNLOADING, JobState.QUEUED):
                        job.state = JobState.FAILED
                        job.error_message = "Server restarted before download completed."
                        job.progress = 0.0
                    self._jobs[job.hash] = job
                except Exception as exc:
                    logger.error("Skipping corrupt job entry: %s", exc)
            logger.info("Loaded %d jobs from %s.", len(self._jobs), JOBS_FILE)
        except Exception as exc:
            logger.error("Failed to load jobs: %s", exc)

        self._loaded = True

    def add(self, job: DownloadJob) -> None:
        self._jobs[job.hash] = job
        self._save()

    def get(self, info_hash: str) -> Optional[DownloadJob]:
        return self._jobs.get(info_hash)

    def get_by_guid(self, guid: str) -> Optional[DownloadJob]:
        needle = hashlib.sha1(guid.encode()).hexdigest()
        return self._jobs.get(needle)

    def remove(self, info_hash: str) -> bool:
        if info_hash in self._jobs:
            del self._jobs[info_hash]
            self._save()
            return True
        return False

    def list_all(self) -> list[DownloadJob]:
        return list(self._jobs.values())

    def update_progress(self, info_hash: str, progress: float, downloaded: int = 0) -> None:
        job = self._jobs.get(info_hash)
        if job is None:
            return
        job.progress = min(progress, 1.0)
        if downloaded:
            job.downloaded = downloaded
        if progress >= 1.0:
            job.state = JobState.COMPLETED
            job.progress = 1.0
        self._save()

    def mark_downloading(self, info_hash: str) -> None:
        job = self._jobs.get(info_hash)
        if job:
            job.state = JobState.DOWNLOADING
            self._save()

    def mark_completed(self, info_hash: str) -> None:
        job = self._jobs.get(info_hash)
        if job:
            job.state = JobState.COMPLETED
            job.progress = 1.0
            self._save()

    def mark_failed(self, info_hash: str, error: str = "") -> None:
        job = self._jobs.get(info_hash)
        if job:
            job.state = JobState.FAILED
            job.error_message = error
            self._save()


store = JobStore()
