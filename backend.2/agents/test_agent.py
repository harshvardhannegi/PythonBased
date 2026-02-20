import os
import subprocess
from typing import Dict, Tuple


class TestAgent:
    def __init__(self):
        self._prepared_repos: Dict[str, Tuple[str, str]] = {}

    def run_tests(self, repo_path):

        repo_path = os.path.abspath(repo_path)
        venv_path = os.path.join(repo_path, ".venv")
        python_bin = os.path.join(venv_path, "bin", "python")
        pip_bin = os.path.join(venv_path, "bin", "pip")

        # Prepare environment once per repo path, but rebuild if repo was cleaned.
        if repo_path in self._prepared_repos and not os.path.exists(python_bin):
            self._prepared_repos.pop(repo_path, None)

        if repo_path not in self._prepared_repos:
            self._run(["python3", "-m", "venv", ".venv"], cwd=repo_path, timeout=60)

            # 🚨 Safety check
            if not os.path.exists(python_bin):
                return "VENV_CREATION_FAILED"

            # 2️⃣ Install deps
            req_file = os.path.join(repo_path, "requirements.txt")

            install_log = ""
            if os.path.exists(req_file):
                req_out, req_rc = self._run(
                    [pip_bin, "install", "-r", req_file], cwd=repo_path, timeout=180
                )
                install_log += req_out or ""
                if req_rc != 0:
                    return "ENV_SETUP_FAILED\n" + install_log

            deps_out, deps_rc = self._run(
                [pip_bin, "install", "pytest", "ruff", "basedpyright"],
                cwd=repo_path,
                timeout=180,
            )
            install_log += deps_out or ""
            if deps_rc != 0:
                return "ENV_SETUP_FAILED\n" + install_log

            self._prepared_repos[repo_path] = (python_bin, pip_bin)

        if not os.path.exists(python_bin):
            return "VENV_CREATION_FAILED"

        # 3️⃣ Run local analyzer/language-server style checks first.
        # Ruff can auto-fix a subset of issues (imports, simple lint rules).
        ruff_out, ruff_rc = self._run(
            [python_bin, "-m", "ruff", "check", "--fix", "."],
            cwd=repo_path,
            timeout=180,
        )
        ruff_text = ruff_out or ""

        # basedpyright provides pyright-compatible static diagnostics.
        pyright_out, pyright_rc = self._run(
            [python_bin, "-m", "basedpyright", "."],
            cwd=repo_path,
            timeout=180,
        )
        pyright_text = pyright_out or ""

        # 4️⃣ Run tests
        test_out, test_rc = self._run([python_bin, "-m", "pytest"], cwd=repo_path, timeout=300)

        # If ruff or pyright emitted text, prepend so bug parsing can use it.
        combined = ruff_text + pyright_text + (test_out or "")

        # Consider success if tests and static types are clean; Ruff nonzero only logs.
        if pyright_rc == 0 and test_rc == 0:
            return None

        return combined

    def _run(self, cmd, cwd=None, timeout=120):
        try:
            completed = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            out = (completed.stdout or "") + (completed.stderr or "")
            return out, completed.returncode
        except subprocess.TimeoutExpired:
            return f"COMMAND_TIMEOUT: {' '.join(cmd)}", 124
        except Exception as exc:
            return f"COMMAND_FAILED: {' '.join(cmd)} :: {exc}", 1
