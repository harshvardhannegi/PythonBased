import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from agents.bug_agent import BugAgent
from agents.fix_agent import FixAgent
from agents.git_agent import GitAgent
from agents.repo_agent import RepoAgent
from agents.test_agent import TestAgent
from utils.event_bus import RuntimeEventBus
from utils.results_manager import ResultsManager
from utils.status_manager import StatusManager


class Orchestrator:
    def __init__(self):

        self.event_bus = RuntimeEventBus()
        self.repo = RepoAgent()
        self.test = TestAgent()
        self.bug = BugAgent()
        self.fix = FixAgent(logger=self._log)
        self.git = GitAgent()
        self.results = ResultsManager()
        self.status_mgr = StatusManager()

        self.timeline = []
        self.fixes = []
        self.status = {"state": "IDLE"}
        self._fix_index = {}
        self._bug_fail_counts = {}
        self.max_bug_attempts = 2

    def _upsert_fixes(self, fixes):
        for item in fixes:
            key = (item["file"], item["bug_type"], item["line"])
            existing_pos = self._fix_index.get(key)

            if existing_pos is None:
                self._fix_index[key] = len(self.fixes)
                self.fixes.append(item)
                continue

            existing = self.fixes[existing_pos]
            # Prefer successful resolution over repeated failures.
            if existing.get("status") != "Fixed" and item.get("status") == "Fixed":
                self.fixes[existing_pos] = item
            else:
                # Keep latest commit message/status for visibility.
                self.fixes[existing_pos] = item

    def run(self, repo_url, team, leader, retry_limit):
        self.timeline = []
        self.fixes = []
        self._fix_index = {}
        self._bug_fail_counts = {}

        started_at = datetime.now(timezone.utc)
        start_time = time.time()
        self.status_mgr.reset(total_iterations=retry_limit, branch="")
        self.status = {
            "state": "RUNNING",
            "started_at": started_at.isoformat(),
        }

        branch = ""
        path = ""
        total_failures = 0
        total_fixes = 0
        total_commits = 0

        try:
            self._log("Cloning repository...")
            self.status_mgr.set_step("Cloning", iteration=0)
            path = self.repo.clone(repo_url)
            branch = self.git.create_branch(path, team, leader)
            self.status_mgr.set_branch(branch)
            self.status_mgr.mark_step("Clone", "Done")

            for i in range(retry_limit):
                run_at = datetime.now(timezone.utc).isoformat()
                self.status_mgr.set_step("Testing", iteration=i + 1)
                failures = self.test.run_tests(path)

                if not failures:
                    self._log(f"Tests run {i + 1}/{retry_limit}: PASSED")
                    self.timeline.append(
                        {
                            "run": i + 1,
                            "status": "PASSED",
                            "timestamp": run_at,
                        }
                    )
                    break

                self.timeline.append(
                    {
                        "run": i + 1,
                        "status": "FAILED",
                        "timestamp": run_at,
                    }
                )
                self._log(f"Tests run {i + 1}/{retry_limit}: FAILED")

                self.status_mgr.set_step("Bug Detection", iteration=i + 1)
                bugs = self.bug.parse(failures)
                self.status_mgr.update_counts(failures=len(bugs))
                if bugs:
                    self._log(f"Detected {len(bugs)} failures")
                    for idx, bug in enumerate(bugs, start=1):
                        self._log(
                            f" Failure #{idx}: {bug['bug_type']} at {bug['file']}:{bug['line']}"
                        )
                else:
                    self._log("Tests failed but no parseable failures; marking UNKNOWN")
                    snippet = "\n".join((failures or "").splitlines()[:5]).strip()
                    if snippet:
                        self._log(f" Raw failure snippet: {snippet}")
                attemptable = []
                skipped = []

                for bug in bugs:
                    key = (bug["file"], bug["bug_type"], bug["line"])
                    failed_attempts = self._bug_fail_counts.get(key, 0)
                    if failed_attempts >= self.max_bug_attempts:
                        escalated = dict(bug)
                        escalated["force_groq"] = True
                        escalated["failed_attempts"] = failed_attempts
                        attemptable.append(escalated)
                    else:
                        queued = dict(bug)
                        queued["failed_attempts"] = failed_attempts
                        attemptable.append(queued)

                self.status_mgr.set_step("Fixing", iteration=i + 1)
                fixes = self.fix.apply_fixes(path, attemptable)

                for item in fixes:
                    key = (item["file"], item["bug_type"], item["line"])
                    if item.get("status") == "Fixed":
                        self._bug_fail_counts.pop(key, None)
                    else:
                        self._bug_fail_counts[key] = self._bug_fail_counts.get(key, 0) + 1
                for idx, item in enumerate(fixes, start=1):
                    self._log(
                        f" Fix #{idx}: {item.get('status')} - {item['bug_type']} {item['file']}:{item['line']}"
                    )

                fixes.extend(skipped)

                self.status_mgr.update_counts(
                    fixes_applied=len([f for f in fixes if f["status"] == "Fixed"])
                )
                self.status_mgr.mark_step("Fixing", "Done")

                self.status_mgr.set_step("Commit", iteration=i + 1)
                committed = self.git.commit_push(path, fixes)
                if committed:
                    total_commits += 1
                    self._log(
                        f"Committed fixes: {len([f for f in fixes if f['status'] == 'Fixed'])} "
                        f"(total commits: {total_commits})"
                    )
                else:
                    self._log("No changes to commit")
                self.status_mgr.mark_step("Commit", "Done")

                total_failures += len(bugs)
                total_fixes += len([f for f in fixes if f["status"] == "Fixed"])
                self._upsert_fixes(fixes)

            ended_at = datetime.now(timezone.utc)
            total_time_seconds = int(time.time() - start_time)

            self.results.generate(
                repo_url=repo_url,
                team_name=team,
                leader_name=leader,
                branch=branch,
                failures=total_failures,
                fixes=total_fixes,
                timeline=self.timeline,
                retry_limit=retry_limit,
                total_commits=total_commits,
                total_time_seconds=total_time_seconds,
                started_at=started_at.isoformat(),
                ended_at=ended_at.isoformat(),
            )

            self._archive_repo(path)

            self.status = {
                "state": "COMPLETED",
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "total_time_seconds": total_time_seconds,
            }
            self.status_mgr.set_state("COMPLETED")
            self.status_mgr.set_step("Completed", iteration=len(self.timeline))
        except Exception as exc:
            ended_at = datetime.now(timezone.utc)
            self.status = {
                "state": "FAILED",
                "error": str(exc),
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "total_time_seconds": int(time.time() - start_time),
            }
            self.status_mgr.set_state("FAILED", error=str(exc))
        finally:
            # Never leave RUNNING state hanging.
            if self.status.get("state") == "RUNNING":
                self.status["state"] = "FAILED"
                self.status["error"] = "Unknown termination"
                self.status_mgr.set_state("FAILED", error="Unknown termination")

            # Always clean the working repo so the next run clones fresh.
            try:
                if path:
                    self.git.cleanup_repo(path)
            except Exception:
                pass

    def _archive_repo(self, repo_path: str):
        if not repo_path:
            return

        root = Path(repo_path)
        if not root.exists():
            return

        results_dir = Path("results")
        results_dir.mkdir(parents=True, exist_ok=True)
        archive_path = results_dir / "fixed_repo.zip"

        skip_dirs = {".git", ".venv", "__pycache__", ".pytest_cache", "node_modules"}

        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in root.rglob("*"):
                if not file_path.is_file():
                    continue

                rel = file_path.relative_to(root)
                if any(part in skip_dirs for part in rel.parts):
                    continue

                archive.write(file_path, rel.as_posix())

    def _log(self, message: str):
        print(f"[AGENT] {message}")
        self.event_bus.publish("log", message)
