import os
import subprocess

from git import Repo


class GitAgent:
    """Git helper with safe defaults and minimal side effects."""

    def _ensure_safe_directory(self, path: str) -> None:
        abs_path = os.path.abspath(path)
        # Ignore failures; only needed when repo owners differ.
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", abs_path],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )

    # -----------------------------
    # Create new branch
    # -----------------------------
    def create_branch(self, path: str, team: str, leader: str) -> str:
        self._ensure_safe_directory(path)

        repo = Repo(path)

        # Ensure we're on main/master first
        try:
            repo.git.checkout("main")
        except Exception:
            repo.git.checkout("master")

        branch = f"{team}_{leader}_AI_Fix".upper().replace(" ", "_")

        # Reuse existing branch if present, else create it.
        existing = {head.name for head in repo.heads}
        if branch in existing:
            repo.git.checkout(branch)
        else:
            repo.git.checkout("-b", branch)

        return branch

    # -----------------------------
    # Commit + Push fixes
    # -----------------------------
    def commit_push(self, path: str, fixes) -> bool:
        self._ensure_safe_directory(path)

        repo = Repo(path)

        # Stage changes
        repo.git.add(A=True)

        # Commit if there are changes
        if repo.is_dirty():
            repo.index.commit("[AI-AGENT] Applied automated fixes")
        else:
            return False

        # Try push; swallow network/permission errors so pipeline can continue.
        try:
            repo.git.push("--set-upstream", "origin", repo.active_branch.name)
        except Exception:
            pass

        return True

    def cleanup_repo(self, path: str) -> None:
        # Best-effort removal of the working repo to force a fresh clone next run.
        try:
            repo = Repo(path)
            repo.close()
        except Exception:
            pass
        try:
            subprocess.run(
                ["rm", "-rf", path],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        except Exception:
            pass
