"""The one job worker of the web interface: every call into cdlbib.api, reads included, runs
here, one at a time, in the order it was asked for. Request threads only enqueue a job and
wait for it or hand out its id.

Admission is bounded: at most MAX_PENDING jobs wait at a time, a job whose repeat is
pointless (a refresh, the preparation) is not queued twice, a job that has not started can
be cancelled, and finished jobs are forgotten after EXPIRY seconds."""
import collections
import secrets
import threading
import time

MAX_LINES = 20_000      # progress lines kept per job; later ones are counted, not kept
KEPT = 300              # finished jobs kept for polling
EXPIRY = 900            # seconds a finished job is kept
# One page asks for fewer than ten things when it opens and one or two per action, and each
# waits for its answer; 32 waiting jobs leave room for several open tabs while bounding
# both the memory held and how long the last one would wait.
MAX_PENDING = 32
STOP_WAIT = 30          # seconds stop() waits for the job that is running


class Busy(Exception):
    """Too many jobs are waiting (HTTP 429)."""


class Closed(Exception):
    """The server is shutting down; nothing more is taken (HTTP 503)."""


class Job:
    def __init__(self, label):
        self.id = secrets.token_urlsafe(16)
        self.label = label
        self.lines, self.dropped = [], 0
        self.done, self.result, self.error = False, None, None
        self.started = self.finished = None
        self.cancelled = False
        self.changed = threading.Condition()

    def say(self, line):
        with self.changed:
            for part in str(line).splitlines() or [""]:
                if len(self.lines) < MAX_LINES:
                    self.lines.append(part)
                else:
                    self.dropped += 1
            self.changed.notify_all()

    def finish(self, result=None, error=None):
        with self.changed:
            if self.done:
                return
            self.result, self.error, self.done, self.finished = result, error, True, time.monotonic()
            self.changed.notify_all()

    def wait(self, seconds):
        """True when the job is done within ``seconds``."""
        with self.changed:
            return self.changed.wait_for(lambda: self.done, timeout=seconds)

    def view(self, after=0, seconds=0.0):
        """What a poll is given: the lines from ``after`` on, and the outcome when there is
        one. Waits up to ``seconds`` for something new."""
        with self.changed:
            self.changed.wait_for(lambda: self.done or len(self.lines) > after, timeout=seconds)
            after = max(0, min(after, len(self.lines)))
            found = {"job": self.id, "label": self.label, "lines": self.lines[after:], "next": len(self.lines),
                     "done": self.done, "running": self.started is not None and not self.done}
            if self.dropped:
                found["dropped"] = self.dropped
            if self.done:
                found["error" if self.error is not None else "result"] = (
                    self.error if self.error is not None else self.result)
            return found


class Worker:
    """A single thread and a bounded queue. ``failure`` turns an exception into the error
    data a job reports."""

    def __init__(self, failure):
        self.failure = failure
        self.waiting = collections.deque()      # (job, call) not yet started
        self.jobs, self.lock = {}, threading.Lock()
        self.wake = threading.Condition(self.lock)
        self.running = None             # the label of the job being run
        self.overlaps = 0               # how often a job started while another ran: stays 0
        self.history = []               # (label, start, end) of every job, by the monotonic clock
        self.thread = threading.Thread(target=self._run, name="cdlbib-web-jobs", daemon=True)
        self.stopped = False

    def start(self):
        self.thread.start()

    def idle(self):
        with self.lock:
            return not self.waiting and self.running is None

    def stop(self, wait=STOP_WAIT):
        """Take nothing more, cancel what has not started, and wait (up to ``wait`` seconds)
        for the job that is running. True when the worker has ended."""
        with self.lock:
            self.stopped = True
            dropped = [job for job, _ in self.waiting]
            self.waiting.clear()
            self.wake.notify_all()
        for job in dropped:
            job.cancelled = True
            job.finish(error={"kind": "Cancelled", "message": "The server is stopping; this was not started."})
        if self.thread.is_alive():
            self.thread.join(wait)
        return not self.thread.is_alive()

    def _forget(self):
        now = time.monotonic()
        finished = sorted((job for job in self.jobs.values() if job.done), key=lambda job: job.finished)
        old = [job for job in finished if now - job.finished > EXPIRY] + finished[:max(0, len(finished) - KEPT)]
        for job in old:
            self.jobs.pop(job.id, None)

    def submit(self, label, call, single=False):
        """Queue ``call(say)``; returns the Job. ``single``: when a job of this label is
        already waiting, that job is returned instead of a second one. Busy when MAX_PENDING
        jobs are waiting; Closed after stop()."""
        with self.lock:
            if self.stopped:
                raise Closed("the server is stopping")
            if single:
                for job, _ in self.waiting:
                    if job.label == label:
                        return job
            if len(self.waiting) >= MAX_PENDING:
                raise Busy(f"{len(self.waiting)} requests are already waiting for the one that is running "
                           f"({self.running or 'none'}); try again when it has finished")
            job = Job(label)
            self.jobs[job.id] = job
            self._forget()
            self.waiting.append((job, call))
            self.wake.notify_all()
        return job

    def cancel(self, job_id):
        """Cancel a job that has not started. "cancelled", "running", "done" or None (no such job)."""
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return None
            for item in self.waiting:
                if item[0] is job:
                    self.waiting.remove(item)
                    break
            else:
                return "done" if job.done else "running"
        job.cancelled = True
        job.finish(error={"kind": "Cancelled", "message": "Cancelled before it started; nothing was done."})
        return "cancelled"

    def get(self, job_id):
        with self.lock:
            return self.jobs.get(job_id)

    def _run(self):
        while True:
            with self.lock:
                while not self.waiting and not self.stopped:
                    self.wake.wait()
                if self.stopped:
                    return
                job, call = self.waiting.popleft()
                if self.running is not None:
                    self.overlaps += 1
                self.running = job.label
                job.started = time.monotonic()
            try:
                result = call(job.say)
            except BaseException as exc:    # a job never takes the worker down with it
                job.finish(error=self.failure(exc))
            else:
                job.finish(result=result)
            with self.lock:
                self.running = None
                self.history.append((job.label, job.started, job.finished))
                del self.history[:-2000]
