"""Regression test for a real bug: build_scheduler() passed next_run_time=None
to APScheduler's add_job(), which per its own docs means "add the job as
paused" - the interval job would never fire a second time, no matter how long
the process ran. Fixed by letting the trigger compute its own first run time."""
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from monitoring.scheduler import build_scheduler


class _FakeApp:
    def app_context(self):
        import contextlib
        return contextlib.nullcontext()


def test_monitoring_job_is_not_added_paused():
    scheduler = build_scheduler(_FakeApp())
    # Scheduler hasn't started, so the job sits in _pending_jobs - inspect the
    # trigger directly rather than job.next_run_time (only set once "really"
    # added by scheduler.start(), which would block this test forever).
    pending = scheduler._pending_jobs
    assert len(pending) == 1
    job = pending[0][0]
    next_fire = job.trigger.get_next_fire_time(None, datetime.now(timezone.utc))
    assert next_fire is not None, "job's trigger produces no next run time - it would never fire"
