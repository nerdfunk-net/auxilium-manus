"""S6-02: the .dockerignore Docker actually reads keeps local environment files out of images."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def test_root_dockerignore_excludes_env_files() -> None:
    lines = {
        line.strip()
        for line in (REPO / ".dockerignore").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert {"**/.env", "**/.env.*", "!**/.env.example"} <= lines
    assert "/data" in lines
    assert "**/.next" in lines


def test_no_dead_dockerignore_in_the_docker_directory() -> None:
    # Build context is the repository root, so docker/.dockerignore is never read.
    assert not (REPO / "docker" / ".dockerignore").exists()
