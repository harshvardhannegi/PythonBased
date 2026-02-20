import os
import re
import subprocess
from functools import lru_cache

from agents.groq_ai_agent import GroqAIAgent


class FixAgent:
    def __init__(self, logger=None):
        self.groq = GroqAIAgent()
        self._logger = logger

    def apply_fixes(self, repo_path, bugs):

        fixes = []

        for bug in bugs:
            bug_type = bug["bug_type"]
            file_path = os.path.join(repo_path, bug["file"])
            fixed = False

            if bug_type == "SYNTAX" and os.path.exists(file_path):
                fixed = self.fix_syntax_issue(file_path, bug["line"])
            elif bug_type == "INDENTATION" and os.path.exists(file_path):
                fixed = self.fix_indentation_issue(file_path, bug["line"])
            elif bug_type == "LINTING" and os.path.exists(file_path):
                fixed = self.fix_with_ruff(repo_path, bug["file"])
            elif bug_type == "TYPE_ERROR" and os.path.exists(file_path):
                fixed = self.fix_type_error(file_path, bug["line"])
            elif bug_type == "LOGIC" and os.path.exists(file_path):
                fixed = self.fix_logic_issue(file_path, bug["line"])
            elif bug_type == "IMPORT":
                fixed = self.fix_missing_init(repo_path, bug["file"])

            used_groq = False
            if not fixed and bug_type != "UNKNOWN" and bug["file"] != "<unknown>":
                used_groq = True
                self._log(
                    f"[AGENT][GROQ] Attempting fix for {bug_type} at {bug['file']}:{bug['line']} "
                    f"(timeout {self.groq.timeout}s)"
                )
                fixed = self.groq.fix_file(file_path, bug_type, bug["line"])
                if fixed:
                    self._log("[AGENT] Fix applied")
                else:
                    self._log("[AGENT] Fix failed, no changes, or timed out")
            elif bug_type == "UNKNOWN" or bug["file"] == "<unknown>":
                self._log("[AGENT] Skipping Groq for UNKNOWN failure; no concrete file/line target")

            if fixed:
                prefix = "[AI-AGENT]" if used_groq else "[AI-AGENT]"
                commit_message = f"{prefix} Fix {bug_type} error"
            else:
                commit_message = f"[AI-AGENT] Could not auto-fix {bug_type}"

            fixes.append(
                {
                    "file": bug["file"],
                    "bug_type": bug_type,
                    "line": bug["line"],
                    "status": "Fixed" if fixed else "Failed",
                    "commit_message": commit_message,
                }
            )

        return fixes

    # -----------------------------
    # FIX 1 - Syntax
    # -----------------------------
    def fix_syntax_issue(self, file_path, line_no):

        with open(file_path, "r") as f:
            lines = f.readlines()

        if line_no <= 0 or line_no > len(lines):
            return False

        changed = False
        line = lines[line_no - 1]

        # Common broken import patterns: duplicate commas / accidental trailing colon
        if line.lstrip().startswith(("import ", "from ")):
            cleaned = line.rstrip()
            cleaned = re.sub(r",\s*,+", ", ", cleaned)
            cleaned = re.sub(r"\s*:\s*$", "", cleaned)
            cleaned = re.sub(r",\s*$", "", cleaned)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()

            # Normalize comma spacing in import lists.
            if cleaned.startswith("import "):
                head, tail = cleaned.split("import ", 1)
                modules = [m.strip() for m in tail.split(",") if m.strip()]
                if modules:
                    cleaned = f"{head}import {', '.join(modules)}".strip()

            if cleaned != line.rstrip():
                lines[line_no - 1] = cleaned + "\n"
                changed = True

        # Missing colon in blocks/defs
        current = lines[line_no - 1]
        stripped = current.strip()
        colon_targets = (
            "def ",
            "class ",
            "if ",
            "elif ",
            "else",
            "for ",
            "while ",
            "try",
            "except ",
            "finally",
            "with ",
        )
        if stripped.startswith(colon_targets) and not stripped.endswith(":"):
            lines[line_no - 1] = current.rstrip() + ":\n"
            changed = True

        if not changed:
            return False

        with open(file_path, "w") as f:
            f.writelines(lines)
        return True

    # -----------------------------
    # FIX 1b - Indentation / Tabs
    # -----------------------------
    def fix_indentation_issue(self, file_path, line_no):

        with open(file_path, "r") as f:
            lines = f.readlines()

        if line_no <= 0 or line_no > len(lines):
            return False

        changed = False
        original = lines[line_no - 1]
        updated = original.replace("\t", "    ")
        if updated != original:
            changed = True

        # If previous line opens a block and current line is not indented, indent it.
        if line_no > 1 and lines[line_no - 2].rstrip().endswith(":"):
            if updated.strip() and not updated.startswith((" ", "\t")):
                updated = "    " + updated
                changed = True

        lines[line_no - 1] = updated
        if not changed:
            return False

        with open(file_path, "w") as f:
            f.writelines(lines)
        return True

    # -----------------------------
    # FIX 2 - Lint / Import Cleanup via Ruff
    # -----------------------------
    def fix_with_ruff(self, repo_path, rel_file):
        target_file = os.path.join(repo_path, rel_file)
        if not os.path.exists(target_file):
            return False

        before = ""
        with open(target_file, "r") as f:
            before = f.read()

        python_bin = self._cached_python(repo_path)
        if not os.path.exists(python_bin):
            return False

        self._run_safe([python_bin, "-m", "ruff", "check", "--fix", rel_file], repo_path)

        with open(target_file, "r") as f:
            after = f.read()

        return before != after

    # -----------------------------
    # FIX 3 - Runtime Type Errors
    # -----------------------------
    def fix_type_error(self, file_path, line_no):
        with open(file_path, "r") as f:
            lines = f.readlines()

        if line_no <= 0 or line_no > len(lines):
            return False

        changed = False
        line = lines[line_no - 1]

        # If arithmetic uses quoted numbers, coerce to numeric literals.
        normalized = re.sub(
            r'([+\-*/%]\s*)["\'](-?\d+(?:\.\d+)?)["\']',
            r"\1\2",
            line,
        )
        if normalized != line:
            line = normalized
            changed = True

        # If int(...) conversion is failing for float-like strings, attempt float-first cast.
        if "int(" in line and "int(float(" not in line:
            wrapped = re.sub(r"int\(([^()]+)\)", r"int(float(\1))", line)
            if wrapped != line:
                line = wrapped
                changed = True

        if not changed:
            return False

        lines[line_no - 1] = line
        with open(file_path, "w") as f:
            f.writelines(lines)
        return True

    # -----------------------------
    # FIX 4 - Runtime Logic Errors
    # -----------------------------
    def fix_logic_issue(self, file_path, line_no):
        with open(file_path, "r") as f:
            lines = f.readlines()

        if line_no <= 0 or line_no > len(lines):
            return False

        line = lines[line_no - 1]
        changed = False

        # Convert direct dict indexing in return paths to safe access.
        # Example: return cfg[key] -> return cfg.get(key)
        safe_get = re.sub(
            r"^(\s*return\s+)([A-Za-z_]\w*)\[(.+)\](\s*)$",
            r"\1\2.get(\3)\4",
            line,
        )
        if safe_get != line:
            line = safe_get
            changed = True

        # Prefer true division when floor-division causes assertion mismatches.
        if "//" in line:
            line = line.replace("//", "/")
            changed = True

        if not changed:
            return False

        lines[line_no - 1] = line
        with open(file_path, "w") as f:
            f.writelines(lines)
        return True

    # -----------------------------
    # FIX 5 - Missing __init__.py
    # -----------------------------
    def fix_missing_init(self, repo_path, module_file):

        module_dir = os.path.dirname(os.path.join(repo_path, module_file))
        if not module_dir:
            return False

        init_file = os.path.join(module_dir, "__init__.py")

        if os.path.exists(init_file):
            return False

        open(init_file, "w").close()
        return True

    # -----------------------------
    # Helpers
    # -----------------------------
    @staticmethod
    @lru_cache(maxsize=16)
    def _cached_python(repo_path):
        venv_path = os.path.join(repo_path, ".venv")
        return os.path.join(venv_path, "bin", "python")

    def _run_safe(self, cmd, repo_path, timeout=180):
        try:
            subprocess.run(
                cmd,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return False
        return True

    def _log(self, message: str):
        if callable(self._logger):
            self._logger(message)
        else:
            print(message)
