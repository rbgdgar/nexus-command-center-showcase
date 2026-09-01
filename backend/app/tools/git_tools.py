import subprocess


def _run_git(arguments: list[str]) -> dict:
    """Run a safe read-only Git command."""

    try:
        result = subprocess.run(
            ["git", *arguments],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        return {
            "command": "git " + " ".join(arguments),
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "return_code": result.returncode,
        }

    except FileNotFoundError:
        return {
            "error": "Git is not installed or is not available in PATH."
        }

    except subprocess.TimeoutExpired:
        return {
            "error": "Git command timed out."
        }


def get_git_status() -> dict:
    """Return the current Git working tree status."""
    return _run_git(["status", "--short", "--branch"])


def get_git_branch() -> dict:
    """Return the current Git branch."""
    return _run_git(["branch", "--show-current"])


def get_recent_commits(limit: int = 5) -> dict:
    """Return recent Git commits."""

    safe_limit = max(1, min(limit, 20))

    return _run_git(
        [
            "log",
            f"-{safe_limit}",
            "--pretty=format:%h | %an | %ad | %s",
            "--date=short",
        ]
    )


def get_git_diff() -> dict:
    """Return unstaged Git changes."""
    return _run_git(["diff", "--stat"])