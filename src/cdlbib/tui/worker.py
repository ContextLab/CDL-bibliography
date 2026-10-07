"""The one job worker. Every call into cdlbib.api runs here, one at a time, on one thread.

A job is a function of one argument (the ``Running`` it is run as: ``progress(line)`` for the
log, ``confirm(question)`` to ask the person). Its result is handed to ``done`` on the
interface's thread, its CdlbibError to ``failed``. A job runs inside api.attempt: when it
stops for a missing optional package or a missing fork, the core decides whether to go on
(by default yes, saying so; with --ask its question is put to the person) and the job is run
again, once.
"""
import queue
import threading
import time

from .. import api
from ..errors import CdlbibError, NeedsConfirmation


class Job:
    def __init__(self, label, call, done=None, failed=None, key=None, quiet=False):
        self.label, self.call, self.done, self.failed, self.key, self.quiet = label, call, done, failed, key, quiet
        self.dropped = False


class Running:
    """What a job is given."""

    def __init__(self, runner, job):
        self.runner, self.job = runner, job
        self.allow_fork = False      # the core let this run create the user's fork (api.attempt)

    def progress(self, line):
        """A line for the log. It never raises: a log that cannot be written to must not stop
        the core's work part-way."""
        try:
            self.runner.say(str(line))
        except Exception:
            pass

    def confirm(self, question):
        """Ask the person yes or no; the job waits for the answer (False when it cannot be asked)."""
        return self.runner.ask(question)


class Runner:
    """``on_ui(function, *args)`` runs a function on the interface's thread and waits for it;
    ``say(line)`` adds a line to the log from any thread; ``ask(question)`` shows a yes/no
    dialog and returns the answer; ``changed()`` is told when the queue's state changes."""

    def __init__(self, on_ui, say, ask, changed=None, unexpected=None):
        self.on_ui, self.say, self.ask = on_ui, say, ask
        self.changed, self.unexpected = changed or (lambda: None), unexpected or (lambda label, exc: None)
        self.queue = queue.Queue()
        self.lock = threading.Lock()
        self.pending = []            # the jobs not yet started, in order
        self.current = None          # the job being run
        self.active = 0              # how many jobs are being run now (0 or 1)
        self.most_active = 0         # the most that ever ran at once (stays 1)
        self.history = []            # (label, started, ended) of each finished job
        self.stopped = False
        self.thread = threading.Thread(target=self._loop, name="cdlbib-jobs", daemon=True)
        self.thread.start()

    # --- the interface's side --------------------------------------------------------------

    def submit(self, label, call, done=None, failed=None, key=None, quiet=False):
        """Queue a job. ``key``: a queued job with the same key that has not started is
        dropped (only the newest search, the newest detail, is worth running)."""
        job = Job(label, call, done, failed, key, quiet)
        with self.lock:
            if key is not None:
                for earlier in self.pending:
                    if earlier.key == key:
                        earlier.dropped = True
                self.pending = [earlier for earlier in self.pending if not earlier.dropped]
            self.pending.append(job)
        self.queue.put(job)
        self.changed()
        return job

    @property
    def idle(self):
        with self.lock:
            return self.current is None and not self.pending

    @property
    def busy_label(self):
        with self.lock:
            return self.current.label if self.current else (self.pending[0].label if self.pending else None)

    @property
    def waiting(self):
        with self.lock:
            return len(self.pending)

    def stop(self):
        self.stopped = True
        self.queue.put(None)

    # --- the worker's side -----------------------------------------------------------------

    def _loop(self):
        while True:
            job = self.queue.get()
            if job is None or self.stopped:
                return
            with self.lock:
                if job.dropped:
                    continue
                self.pending.remove(job)
                self.current = job
                self.active += 1
                self.most_active = max(self.most_active, self.active)
            started = time.monotonic()
            self._safely(job.label, self.changed)
            try:
                self._run(job)
            except Exception as exc:        # nothing a job or its callbacks do ends the one worker
                self._error(job.label, exc)
            finally:
                with self.lock:
                    self.active -= 1
                    self.current = None
                    self.history.append((job.label, started, time.monotonic()))
                self._safely(job.label, self.changed)

    def _error(self, label, exc):
        try:
            self.say(f"error: {label}: {type(exc).__name__}: {exc}")
        except Exception:
            pass

    def _safely(self, label, function, *args):
        """Run a callback on the interface's thread; an exception it raises is an error line in
        the log, and the worker goes on to the next job."""
        try:
            self._tell(function, *args)
        except Exception as exc:
            self._error(label, exc)

    def _tell(self, function, *args):
        if self.stopped:
            return
        try:
            self.on_ui(function, *args)
        except Exception:       # the interface is closing; there is nobody to tell
            if not self.stopped:
                raise

    def _run(self, job):
        running = Running(self, job)
        if not job.quiet:
            self.say(f"> {job.label}")
        def run(allow_fork_creation=False):
            running.allow_fork = allow_fork_creation
            return job.call(running)
        answers = {}
        while True:
            try:
                # api.attempt installs a missing package or lets the fork be made, once each, and
                # runs the job again; whether to is the core's decision (asked first with --ask).
                result = api.attempt(run, allow_install=answers.get("install"), allow_fork=answers.get("fork"),
                                     progress=running.progress)
            except NeedsConfirmation as exc:
                if exc.kind in answers:              # asked already: the core's refusal stands
                    self._failed(job, exc)
                    return
                answers[exc.kind] = bool(self.ask(exc.question))
                continue
            except CdlbibError as exc:
                self._failed(job, exc)
                return
            except Exception as exc:        # not a failure the core reports: shown, never swallowed
                self._error(job.label, exc)
                self._safely(job.label, self.unexpected, job.label, exc)
                return
            if job.done:
                self._safely(job.label, job.done, result)
            return

    def _failed(self, job, exc):
        self.say(str(exc))
        if job.failed:
            self._safely(job.label, job.failed, exc)
        else:
            self._safely(job.label, self.unexpected, job.label, exc)
