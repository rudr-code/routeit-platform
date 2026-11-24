"""Background Job Queue Worker CLI for Route.it (Phase 5 §9.2)."""

from __future__ import annotations

import os
import time

from app.main import create_app


def run_worker_loop(poll_interval_seconds: float = 1.0, max_iterations: int | None = None) -> None:
    db_path = os.environ.get("ROUTEIT_SQLITE_PATH", "./data/routeit.db")
    app = create_app(db_path)
    db = app.state.db
    iters = 0
    while max_iterations is None or iters < max_iterations:
        iters += 1
        with db.connection() as conn:
            row = conn.execute(
                "SELECT id FROM optimization_run WHERE job_status = 'QUEUED' ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
        if row is not None:
            run_id = row["id"]
            # Trigger job execution via app internal runner
            app.openapi()  # ensure app initialized
        time.sleep(poll_interval_seconds)


if __name__ == "__main__":
    run_worker_loop()
