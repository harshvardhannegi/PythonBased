import os
import shutil
import stat

from git import Repo


class RepoAgent:
    """Simple repo clone with clean overwrite."""

    def remove_readonly(self, func, path, _):
        os.chmod(path, stat.S_IWRITE)
        func(path)

    def clone(self, repo_url: str) -> str:

        base = "workspace"
        path = os.path.join(base, "repo")

        os.makedirs(base, exist_ok=True)

        # Always fully delete existing repo
        if os.path.exists(path):
            shutil.rmtree(path, onerror=self.remove_readonly)

        # Fresh clone every run
        Repo.clone_from(
            repo_url,
            path,
            depth=1,
            no_single_branch=True,
        )

        return path
