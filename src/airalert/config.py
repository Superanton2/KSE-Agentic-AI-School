"""Runtime settings read from environment / .env (never log secrets)."""

from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

VADIMKIN_REPO_URL = "https://github.com/Vadimkin/ukrainian-air-raid-sirens-dataset"
OFFICIAL_CHANNEL = "air_alert_ua"
VOLUNTEER_CHANNEL = "UkraineAlarmSignal"
LIVE_CHANNELS = [OFFICIAL_CHANNEL, VOLUNTEER_CHANNEL]
HEARTBEAT_MAX_AGE_SECONDS = 300
KYIV = "Kyiv City"
SITREP_URL = "https://alerts.in.ua/llm"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    tg_api_id: int | None = None
    tg_api_hash: SecretStr | None = None
    tg_session_path: Path = Path("~/.config/airalert/airalert.session")
    data_dir: Path = Path("data")
    reports_dir: Path = Path("reports")
    # Drone-monitoring channels (comma-separated), collected by the same tg-live process into drones.sqlite.
    tg_drone_channels: str = "kudy_letyt,kpszsu,kyiv_nebo"
    # On the first start tg-live downloads drone-channel history from this UTC date (regime change ~08-17).
    tg_drone_since: datetime = datetime(2026, 8, 10, tzinfo=UTC)
    sitrep_url: str = SITREP_URL
    sitrep_poll_seconds: int = 60
    # Put a way to reach the project here (email/URL); it goes into the SITREP User-Agent.
    sitrep_contact: str = ""

    @field_validator("tg_drone_since")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)

    @property
    def drone_channels(self) -> list[str]:
        return [c.strip() for c in self.tg_drone_channels.split(",") if c.strip()]

    @property
    def session_path(self) -> Path:
        return self.tg_session_path.expanduser().resolve()

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def dataset_dir(self) -> Path:
        return self.raw_dir / "vadimkin"

    @property
    def live_dir(self) -> Path:
        return self.data_dir / "live"

    @property
    def sqlite_path(self) -> Path:
        return self.live_dir / "alerts.sqlite"

    @property
    def drones_sqlite_path(self) -> Path:
        return self.live_dir / "drones.sqlite"

    @property
    def sitrep_sqlite_path(self) -> Path:
        return self.live_dir / "sitrep.sqlite"

    def db_for_channel(self, channel: str) -> Path:
        return self.drones_sqlite_path if channel in self.drone_channels else self.sqlite_path

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"


@lru_cache
def get_settings() -> Settings:
    return Settings()
