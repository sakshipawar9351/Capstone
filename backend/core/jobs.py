"""
Background jobs — so a long analysis does not have to finish inside a request.

Why this exists
---------------
A site-tier analysis is 2.25 M cells: terrain derivatives, slip, hazard, cost,
then seven planners over the result. Measured end to end at Connecting Ridge
that is 35-150 s. Nothing about that is wrong, but it cannot be the body of an
HTTP request — browsers and proxies time out long before it lands, and a user
watching a spinner has no idea whether the work is progressing or dead.

So work is *submitted*, not awaited. The caller gets an id immediately, polls,
and sees progress while it runs.

Deduplication is the point, not a bonus
---------------------------------------
Jobs carry a ``key`` — for an AOI, its cache key. Submitting the same key twice
returns the *same job* rather than starting a second one. Two users opening the
same region, or one user double-clicking, must not launch two 150-second
analyses of identical ground. A finished job keeps its result, so re-opening a
region is instant.

A *failed* job is deliberately not deduplicated: resubmitting after a failure
retries, because the failure may have been transient and refusing to retry
would strand the region forever.

Threads, not processes
----------------------
The work is numpy and scipy, which release the GIL for the array operations
that dominate the runtime, so threads genuinely run in parallel here. Processes
would isolate CPU better but would have to pickle multi-hundred-megabyte
rasters across a boundary, and on Windows would re-import the world per worker.
Threads are the right trade for this workload.

No database
-----------
The registry is in-memory and bounded. Jobs describe work in flight, which does
not outlive the process; the *artifacts* a job produces are what deserve
persistence, and those belong to the AOI, not to the job that made them.
"""

from __future__ import annotations

import itertools
import os
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum

__all__ = ["JobState", "Job", "JobQueue", "default_queue"]


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"

    @property
    def finished(self) -> bool:
        return self in (JobState.DONE, JobState.FAILED)


#: Signature a unit of work must accept: ``progress(fraction, message)``.
Progress = Callable[[float, str], None]


@dataclass
class Job:
    """One unit of work, and everything a caller needs to follow it."""

    id: str
    kind: str
    key: str | None
    state: JobState = JobState.QUEUED
    progress: float = 0.0
    message: str = "queued"
    submitted_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result: object | None = None
    error: str | None = None
    meta: dict = field(default_factory=dict)

    @property
    def elapsed_s(self) -> float:
        if self.started_at is None:
            return 0.0
        return (self.finished_at or time.time()) - self.started_at

    @property
    def waited_s(self) -> float:
        return (self.started_at or time.time()) - self.submitted_at

    def to_dict(self, *, include_result: bool = True) -> dict:
        d = {
            "id": self.id,
            "kind": self.kind,
            "key": self.key,
            "state": self.state.value,
            "progress": round(self.progress, 4),
            "message": self.message,
            "waited_s": round(self.waited_s, 3),
            "elapsed_s": round(self.elapsed_s, 3),
            "meta": self.meta,
        }
        if self.state is JobState.FAILED:
            d["error"] = self.error
        if include_result and self.state is JobState.DONE:
            d["result"] = self.result
        return d


class JobQueue:
    """A bounded pool with a deduplicating registry."""

    def __init__(self, workers: int = 2, retain: int = 64):
        self._pool = ThreadPoolExecutor(max_workers=workers,
                                        thread_name_prefix="ls-job")
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._by_key: dict[str, str] = {}
        self._retain = retain
        self._seq = itertools.count(1)

    # -- submission ------------------------------------------------------

    def submit(self, kind: str, fn: Callable[[Progress], object], *,
               key: str | None = None, meta: dict | None = None) -> Job:
        """Queue work and return immediately.

        ``fn`` receives one argument, a ``progress(fraction, message)``
        callable. Anything it returns becomes the job's result.

        If ``key`` names work already queued, running or completed, that job is
        returned untouched and ``fn`` is never called.
        """
        with self._lock:
            if key is not None:
                existing = self._live_by_key(key)
                if existing is not None:
                    return existing

            job = Job(id=f"{kind}-{next(self._seq):04d}-{uuid.uuid4().hex[:6]}",
                      kind=kind, key=key, meta=dict(meta or {}))
            self._jobs[job.id] = job
            if key is not None:
                self._by_key[key] = job.id
            self._evict()

        self._pool.submit(self._run, job, fn)
        return job

    def _live_by_key(self, key: str) -> Job | None:
        """A prior job for this key, unless it failed — failures may retry."""
        jid = self._by_key.get(key)
        if jid is None:
            return None
        job = self._jobs.get(jid)
        if job is None or job.state is JobState.FAILED:
            self._by_key.pop(key, None)
            return None
        return job

    # -- execution -------------------------------------------------------

    def _run(self, job: Job, fn: Callable[[Progress], object]) -> None:
        def progress(fraction: float, message: str = "") -> None:
            with self._lock:
                job.progress = min(max(float(fraction), 0.0), 1.0)
                if message:
                    job.message = message

        with self._lock:
            job.state = JobState.RUNNING
            job.started_at = time.time()
            job.message = "running"

        try:
            result = fn(progress)
        except Exception as exc:                       # noqa: BLE001
            with self._lock:
                job.state = JobState.FAILED
                # The message a caller can act on, plus the last frame for a
                # developer. A bare repr of the exception loses where it came
                # from; a whole traceback in an API response is noise.
                tb = traceback.extract_tb(exc.__traceback__)
                # os.path.basename, not rsplit('/'), or a Windows path keeps
                # every one of its backslash-separated components.
                where = (f"{os.path.basename(tb[-1].filename)}:{tb[-1].lineno}"
                         if tb else "?")
                job.error = f"{type(exc).__name__}: {exc}  [{where}]"
                job.message = "failed"
                job.finished_at = time.time()
            return

        with self._lock:
            job.state = JobState.DONE
            job.result = result
            job.progress = 1.0
            job.message = "done"
            job.finished_at = time.time()

    # -- inspection ------------------------------------------------------

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def by_key(self, key: str) -> Job | None:
        with self._lock:
            jid = self._by_key.get(key)
            return self._jobs.get(jid) if jid else None

    def list(self, limit: int = 50) -> list[Job]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.submitted_at,
                          reverse=True)
        return jobs[:limit]

    def wait(self, job_id: str, timeout: float = 60.0,
             poll: float = 0.01) -> Job | None:
        """Block until a job finishes. For tests and for synchronous callers."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self.get(job_id)
            if job is None or job.state.finished:
                return job
            time.sleep(poll)
        return self.get(job_id)

    # -- housekeeping ----------------------------------------------------

    def _evict(self) -> None:
        """Drop the oldest finished jobs once the registry is over budget.

        Only finished jobs are eligible: evicting something still running would
        lose the handle to work that is still consuming a worker.
        """
        if len(self._jobs) <= self._retain:
            return
        finished = sorted((j for j in self._jobs.values() if j.state.finished),
                          key=lambda j: j.finished_at or 0.0)
        for job in finished[:len(self._jobs) - self._retain]:
            self._jobs.pop(job.id, None)
            if job.key and self._by_key.get(job.key) == job.id:
                self._by_key.pop(job.key, None)

    def stats(self) -> dict:
        with self._lock:
            by_state: dict[str, int] = {}
            for j in self._jobs.values():
                by_state[j.state.value] = by_state.get(j.state.value, 0) + 1
            return {"jobs": len(self._jobs), "keyed": len(self._by_key),
                    "by_state": by_state}

    def shutdown(self, wait: bool = False) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=not wait)


_DEFAULT: JobQueue | None = None
_DEFAULT_LOCK = threading.Lock()


def default_queue() -> JobQueue:
    """Process-wide queue. Created on first use so importing costs nothing."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = JobQueue()
        return _DEFAULT


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _self_test() -> int:
    npass = nfail = 0

    def check(name, ok, detail=""):
        nonlocal npass, nfail
        if ok:
            npass += 1
            print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
        else:
            nfail += 1
            print(f"  FAIL  {name}   {detail}")

    q = JobQueue(workers=2, retain=8)

    print("\nWork runs off the caller's thread\n")
    started = threading.Event()
    release = threading.Event()

    def slow(progress):
        started.set()
        progress(0.5, "halfway")
        release.wait(5.0)
        return {"answer": 42}

    t0 = time.time()
    job = q.submit("test", slow, key="k1")
    submit_ms = (time.time() - t0) * 1e3
    check("submit returns immediately", submit_ms < 100, f"{submit_ms:.1f} ms")
    check("the job starts queued or running",
          job.state in (JobState.QUEUED, JobState.RUNNING), job.state.value)

    started.wait(5.0)
    time.sleep(0.05)
    check("progress is visible while the job runs",
          q.get(job.id).progress == 0.5 and q.get(job.id).message == "halfway",
          f"{q.get(job.id).progress} / {q.get(job.id).message!r}")

    print("\nThe same key is never run twice\n")
    calls = itertools.count()

    dup = q.submit("test", lambda p: next(calls), key="k1")
    check("resubmitting a live key returns the same job", dup.id == job.id,
          f"{dup.id} == {job.id}")

    release.set()
    done = q.wait(job.id, timeout=5.0)
    check("the job completes", done.state is JobState.DONE, done.state.value)
    check("the result is kept", done.result == {"answer": 42}, str(done.result))
    check("progress ends at 1.0", done.progress == 1.0)

    cached = q.submit("test", lambda p: "SHOULD NOT RUN", key="k1")
    check("a finished key is served from cache, not recomputed",
          cached.id == job.id and cached.result == {"answer": 42},
          "re-opening a region must be instant")

    print("\nFailure is captured, not crashed, and may be retried\n")

    def boom(progress):
        raise ValueError("terrain window contains no valid data")

    bad = q.wait(q.submit("test", boom, key="k2").id, timeout=5.0)
    check("an exception becomes a failed job", bad.state is JobState.FAILED)
    check("the message is actionable", "no valid data" in (bad.error or ""),
          bad.error)
    check("the location is recorded", "jobs.py:" in (bad.error or "")
          or ".py:" in (bad.error or ""), bad.error)

    retry = q.submit("test", lambda p: "recovered", key="k2")
    check("a failed key is retried rather than cached", retry.id != bad.id,
          "refusing to retry would strand the region forever")
    check("the retry succeeds",
          q.wait(retry.id, timeout=5.0).result == "recovered")

    print("\nThe pool is bounded and the registry is evicted\n")

    for i in range(20):
        q.wait(q.submit("bulk", lambda p, i=i: i, key=f"bulk{i}").id, timeout=5.0)
    st = q.stats()
    print(f"    {st}")
    check("the registry stays within its retention budget", st["jobs"] <= 8,
          f"{st['jobs']} retained, budget 8")
    check("evicted keys are released too", st["keyed"] <= st["jobs"],
          "a key pointing at a dropped job would deduplicate against nothing")

    print("\nConcurrency\n")
    n = 6
    barrier_hits = []
    lock = threading.Lock()

    def concurrent(progress):
        with lock:
            barrier_hits.append(time.time())
        time.sleep(0.15)
        return True

    t0 = time.time()
    ids = [q.submit("conc", concurrent, key=f"c{i}").id for i in range(n)]
    for jid in ids:
        q.wait(jid, timeout=10.0)
    wall = time.time() - t0
    serial = n * 0.15
    print(f"    {n} jobs x 0.15 s: wall {wall:.2f} s, serial would be {serial:.2f} s")
    check("two workers actually overlap", wall < serial * 0.85,
          f"{wall:.2f} s vs {serial:.2f} s serial")
    check("every job ran", len(barrier_hits) == n, f"{len(barrier_hits)}/{n}")

    print("\nReporting\n")
    d = done.to_dict()
    check("to_dict carries state, progress and timing",
          {"id", "state", "progress", "elapsed_s"} <= set(d))
    check("a failed job reports its error, not its result",
          "error" in bad.to_dict() and "result" not in bad.to_dict())

    q.shutdown(wait=True)
    print(f"\n{npass} passed, {nfail} failed")
    return 1 if nfail else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
