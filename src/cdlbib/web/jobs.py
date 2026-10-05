"""The one job worker of the web interface: every call into cdlbib.api, reads included, runs
here, one at a time, in the order it was asked for. Request threads only enqueue a job and
wait for it or hand out its id."""
import queue
import secrets
import threading
import time

MAX_LINES = 20_000      # progress lines kept per job; later ones replace nothing, they are counted
KEPT = 300              # finished jobs kept for polling


class Job:
    def __init__(self, label):
        self.id = secrets.token_urlsafe(16)
        self.label = label
        self.lines, self.dropped = [], 0
        self.done, self.result, self.error = False, None, None
        self.started = self.finished = None
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
    """A single thread and a queue. ``failure`` turns an exception into the error data a
    job reports."""

    def __init__(self, failure):
        self.failure = failure
        self.queue = queue.Queue()
        self.jobs, self.lock = {}, threading.Lock()
        self.running = None             # the label of the job being run, for the overlap check
        self.overlaps = 0               # how often a job started while another ran: stays 0
        self.history = []               # (label, start, end) of every job, by the monotonic clock
        self.thread = threading.Thread(target=self._run, name="cdlbib-web-jobs", daemon=True)
        self.stopped = False

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopped = True
        self.queue.put(None)

    def submit(self, label, call):
        """Queue ``call(say)``; returns the Job."""
        job = Job(label)
        with self.lock:
            self.jobs[job.id] = job
            finished = [found for found in self.jobs.values() if found.done]
            for old in sorted(finished, key=lambda found: found.finished)[:max(0, len(finished) - KEPT)]:
                del self.jobs[old.id]
        self.queue.put((job, call))
        return job

    def get(self, job_id):
        with self.lock:
            return self.jobs.get(job_id)

    def _run(self):
        while True:
            item = self.queue.get()
            if item is None or self.stopped:
                return
            job, call = item
            with self.lock:
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
