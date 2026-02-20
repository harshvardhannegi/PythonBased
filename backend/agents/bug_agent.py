import re


class BugAgent:
    def parse(self, logs):

        bugs = []
        seen = set()

        if not logs:
            return bugs

        # -----------------------------
        # SYNTAX ERRORS
        # -----------------------------
        syntax_matches = re.findall(
            r'File "(.+?\.py)", line (\d+).*?SyntaxError',
            logs,
            re.DOTALL,
        )
        for file_path, line in syntax_matches:
            self._add_bug(bugs, seen, file_path, "SYNTAX", int(line))

        # -----------------------------
        # INDENTATION ERRORS
        # -----------------------------
        indentation_matches = re.findall(
            r'File "(.+?\.py)", line (\d+).*?(IndentationError|TabError)',
            logs,
            re.DOTALL,
        )
        for file_path, line, _ in indentation_matches:
            self._add_bug(bugs, seen, file_path, "INDENTATION", int(line))

        # -----------------------------
        # IMPORT ERRORS
        # -----------------------------
        import_matches = re.findall(
            r'File "(.+?\.py)", line (\d+).*?(ModuleNotFoundError|ImportError)',
            logs,
            re.DOTALL,
        )
        for file_path, line, _ in import_matches:
            self._add_bug(bugs, seen, file_path, "IMPORT", int(line))

        # -----------------------------
        # TYPE ERRORS
        # -----------------------------
        type_matches = re.findall(
            r'File "(.+?\.py)", line (\d+).*?(TypeError|ValueError)',
            logs,
            re.DOTALL,
        )
        for file_path, line, _ in type_matches:
            self._add_bug(bugs, seen, file_path, "TYPE_ERROR", int(line))

        # -----------------------------
        # LOGIC ERRORS
        # -----------------------------
        logic_matches = re.findall(
            r'File "(.+?\.py)", line (\d+).*?(NameError|KeyError|AssertionError|AttributeError)',
            logs,
            re.DOTALL,
        )
        for file_path, line, _ in logic_matches:
            self._add_bug(bugs, seen, file_path, "LOGIC", int(line))

        # Pytest short assertion format:
        # path.py:42: AssertionError
        logic_short_matches = re.findall(
            r"(.+?\.py):(\d+):\s*AssertionError",
            logs,
        )
        for file_path, line in logic_short_matches:
            self._add_bug(bugs, seen, file_path, "LOGIC", int(line))

        # -----------------------------
        # LINT / UNUSED IMPORT
        # -----------------------------
        lint_matches = re.findall(
            r"(.+?\.py):(\d+):(?:\d+:)?\s*(?:F401|W0611|.*unused import)",
            logs,
        )
        for file_path, line in lint_matches:
            self._add_bug(bugs, seen, file_path, "LINTING", int(line))

        # -----------------------------
        # basedpyright / pyright diagnostics
        # -----------------------------
        pyright_matches = re.findall(
            r"(.+?\.py):(\d+):(\d+)\s*-\s*error:\s*(.+)",
            logs,
        )
        for file_path, line, _col, message in pyright_matches:
            msg = message.lower()
            if "import" in msg or "cannot be resolved" in msg:
                bug_type = "IMPORT"
            elif "type" in msg or "argument of type" in msg or "cannot assign" in msg:
                bug_type = "TYPE_ERROR"
            elif "syntax" in msg:
                bug_type = "SYNTAX"
            else:
                bug_type = "LOGIC"
            self._add_bug(bugs, seen, file_path, bug_type, int(line))

        # -----------------------------
        # Pytest collection import errors
        # -----------------------------
        collecting_matches = re.findall(
            r"ERROR collecting (.+?\.py).*?ImportError",
            logs,
            re.DOTALL,
        )
        for file_path in collecting_matches:
            self._add_bug(bugs, seen, file_path, "IMPORT", 1)

        # Fallback: if logs indicate failure but nothing parsed, add UNKNOWN bug
        if logs and not bugs:
            self._add_bug(bugs, seen, "<unknown>", "UNKNOWN", 1)

        return bugs

    def _add_bug(self, bugs, seen, file_path, bug_type, line):
        clean = self.clean_path(file_path)
        key = (clean, bug_type, int(line))
        if key in seen:
            return
        seen.add(key)
        bugs.append(
            {
                "file": clean,
                "bug_type": bug_type,
                "line": int(line),
                "status": "Detected",
            }
        )

    # -----------------------------
    # Clean absolute -> repo path
    # -----------------------------
    def clean_path(self, full_path):

        if "workspace/repo/" in full_path:
            return full_path.split("workspace/repo/")[1]

        if "/repo/" in full_path:
            return full_path.split("/repo/")[1]

        return full_path
