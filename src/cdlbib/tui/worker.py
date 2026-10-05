"""The one job worker. Every call into cdlbib.api runs here, one at a time, on one thread.

A job is a function of one argument (the ``Running`` it is run as: ``progress(line)`` for the
log, ``confirm(question)`` to ask the person). Its result is handed to ``done`` on the
interface's thread, its CdlbibError to ``failed``. A job that stops for a missing optional
package has the package installed (after a question with --ask) and is run again, once.
"""
import queue
import threading
import time

from .. import deps
from ..errors import CdlbibError, MissingDependency


class Job:
    def __init__(self, label, call, done=None, failed=None, key=None, quiet=False):
        self.label, self.call, self.done, self.failed, self.key, self.quiet = label, call, done, failed, key, quiet
        self.dropped = False


class Running:
    """What a job is given."""

    def __init__(self, runner, job):
        self.runner, self.job = runner, job

    def progress(self, line):
        self.runner.say(str(line))

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
            self._tell(self.changed)
            try:
                self._run(job)
            finally:
                with self.lock:
                    self.active -= 1
                    self.current = None
                    self.history.append((job.label, started, time.monotonic()))
                self._tell(self.changed)

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
        for attempt in (1, 2):
            try:
                result = job.call(running)
            except MissingDependency as exc:
                if attempt == 1 and self._install(exc):
                    continue
                self._failed(job, exc)
                return
            except CdlbibError as exc:
                self._failed(job, exc)
                return
            except Exception as exc:        # not a failure the core reports: shown, never swallowed
                self.say(f"{job.label}: {type(exc).__name__}: {exc}")
                self._tell(self.unexpected, job.label, exc)
                return
            if job.done:
                self._tell(job.done, result)
            return

    def _failed(self, job, exc):
        self.say(str(exc))
        if job.failed:
            self._tell(job.failed, exc)
        else:
            self._tell(self.unexpected, job.label, exc)

    def _install(self, exc):
        """Install the package a job needs: by default after saying so, with --ask after a
        yes. True when it was installed."""
        if deps.ask():
            if not self.ask(f"{exc.feature} needs '{exc.package}'. Install it now?"):
                return False
        self.say(f"installing {exc.package} (needed for: {exc.feature}) ...")
        try:
            deps.install(exc.extra, package=exc.package)
        except CdlbibError as failure:
            self.say(str(failure))
            return False
        self.say(f"installed {exc.package}")
        return True
