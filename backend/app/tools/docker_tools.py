import subprocess


def _run_docker(arguments: list[str]) -> dict:
    """Run a safe read-only Docker command."""

    try:
        result = subprocess.run(
            ["docker", *arguments],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        return {
            "command": "docker " + " ".join(arguments),
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "return_code": result.returncode,
        }

    except FileNotFoundError:
        return {
            "error": "Docker CLI is not installed or is not available in PATH."
        }

    except subprocess.TimeoutExpired:
        return {
            "error": "Docker command timed out."
        }


def get_docker_version() -> dict:
    """Return Docker version information."""
    return _run_docker(["version", "--format", "{{json .}}"])


def list_docker_containers() -> dict:
    """List currently running Docker containers."""
    return _run_docker(
        [
            "ps",
            "--format",
            "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}",
        ]
    )


def list_docker_images() -> dict:
    """List locally available Docker images."""
    return _run_docker(
        [
            "images",
            "--format",
            "table {{.Repository}}\t{{.Tag}}\t{{.Size}}",
        ]
    )