import threading
from typing import Any, Dict, List, Optional


class StatusManager:
    """Thread-safe runtime status tracker for the pipeline."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state: Dict[str, Any] = {
            "state": "IDLE",
            "current_step": "",
            "iteration": 0,
            "total_iterations": 0,
            "failures": 0,
            "fixes_applied": 0,
            "branch_name": "",
        }
        self.timeline: List[Dict[str, Any]] = []

    def reset(self, total_iterations: int, branch: str = ""):
        with self._lock:
            self._state.update(
                {
                    "state": "RUNNING",
                    "current_step": "Starting",
                    "iteration": 0,
                    "total_iterations": total_iterations,
                    "failures": 0,
                    "fixes_applied": 0,
                    "branch_name": branch,
                }
            )
            self.timeline = []

    def set_step(self, step: str, iteration: Optional[int] = None):
        with self._lock:
            if iteration is not None:
                self._state["iteration"] = iteration
            self._state["current_step"] = step
            self.timeline.append({"step": step, "status": "In-Progress"})

    def mark_step(self, step: str, status: str):
        with self._lock:
            self.timeline.append({"step": step, "status": status})

    def update_counts(self, failures: Optional[int] = None, fixes_applied: Optional[int] = None):
        with self._lock:
            if failures is not None:
                self._state["failures"] = failures
            if fixes_applied is not None:
                self._state["fixes_applied"] = fixes_applied

    def set_state(self, state: str, error: str = ""):
        with self._lock:
            self._state["state"] = state
            if error:
                self._state["error"] = error
            elif "error" in self._state:
                self._state.pop("error", None)

    def set_branch(self, branch: str):
        with self._lock:
            self._state["branch_name"] = branch

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            snap = dict(self._state)
            snap["timeline"] = list(self.timeline)
            return snap
