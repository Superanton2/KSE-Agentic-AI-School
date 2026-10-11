"""Fetch and load the Vadimkin air-raid sirens dataset (MIT)."""

import subprocess
from pathlib import Path

import pandas as pd

from airalert.config import VADIMKIN_REPO_URL

OFFICIAL_COLUMNS = ["oblast", "raion", "hromada", "level", "started_at", "finished_at", "source"]
VOLUNTEER_COLUMNS = ["region", "started_at", "finished_at", "naive"]


def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def fetch(dataset_dir: Path) -> str:
    """Shallow clone (or fast-forward) the dataset repo; return the checked-out commit sha."""
    if (dataset_dir / ".git").exists():
        _git("fetch", "--depth", "1", "origin", cwd=dataset_dir)
        _git("reset", "--hard", "FETCH_HEAD", cwd=dataset_dir)
    else:
        dataset_dir.parent.mkdir(parents=True, exist_ok=True)
        _git("clone", "--depth", "1", VADIMKIN_REPO_URL, str(dataset_dir))
    return commit_info(dataset_dir)["sha"]


def commit_info(dataset_dir: Path) -> dict[str, str]:
    sha, date = _git("log", "-1", "--format=%H %cI", cwd=dataset_dir).split(" ")
    return {"sha": sha, "committed_at": date}


def read_official_raw(dataset_dir: Path) -> pd.DataFrame:
    """CSV as-is: every column a string, empty cells as ''."""
    return pd.read_csv(dataset_dir / "datasets" / "official_data_en.csv", dtype=str, keep_default_na=False)


def read_volunteer_raw(dataset_dir: Path) -> pd.DataFrame:
    return pd.read_csv(dataset_dir / "datasets" / "volunteer_data_en.csv", dtype=str, keep_default_na=False)
