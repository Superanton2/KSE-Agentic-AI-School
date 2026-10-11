"""Command-line entry point: ``airalert <command>``."""

import logging

import pandas as pd
import typer

from airalert import dataset, report, validate
from airalert.config import get_settings

app = typer.Typer(no_args_is_help=True, add_completion=False)
log = logging.getLogger("airalert")


@app.callback()
def _main(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Telethon logs request internals at DEBUG; keep it quiet regardless.
    logging.getLogger("telethon").setLevel(logging.WARNING)


@app.command("fetch-dataset")
def fetch_dataset() -> None:
    """Clone or update the Vadimkin dataset in data/raw/."""
    s = get_settings()
    sha = dataset.fetch(s.dataset_dir)
    typer.echo(f"dataset at {s.dataset_dir} @ {sha}")


def _dataset_frames() -> tuple[validate.DatasetFrames, dict]:
    s = get_settings()
    if not (s.dataset_dir / "datasets").exists():
        raise typer.BadParameter("dataset not found — run `airalert fetch-dataset` first")
    frames = validate.prepare(
        dataset.read_official_raw(s.dataset_dir), dataset.read_volunteer_raw(s.dataset_dir)
    )
    return frames, dataset.commit_info(s.dataset_dir)


@app.command("validate-dataset")
def validate_dataset() -> None:
    """Run dataset checks 1–8 and write reports/data_quality.{md,json}."""
    s = get_settings()
    frames, commit = _dataset_frames()
    checks = validate.run_dataset_checks(frames)
    checks += validate.pending_telegram_checks(
        "Telegram-дані ще не зібрані (потрібен tg-login + tg-backfill)."
    )
    meta = {
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
        "vadimkin_commit": commit["sha"],
        "vadimkin_committed_at": commit["committed_at"],
    }
    md, _ = report.write(checks, meta, s.reports_dir)
    for c in checks:
        typer.echo(f"[{c.status:4}] #{c.id:<2} {c.scope:28} {c.name}: {c.value}")
    typer.echo(f"report: {md}")
    if any(c.status == "FAIL" for c in checks):
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
