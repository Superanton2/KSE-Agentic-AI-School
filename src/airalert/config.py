"""Runtime settings read from environment / .env (never log secrets)."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

VADIMKIN_REPO_URL = "https://github.com/Vadimkin/ukrainian-air-raid-sirens-dataset"
OFFICIAL_CHANNEL = "air_alert_ua"
VOLUNTEER_CHANNEL = "UkraineAlarmSignal"
LIVE_CHANNELS = [OFFICIAL_CHANNEL, VOLUNTEER_CHANNEL]
HEARTBEAT_MAX_AGE_SECONDS = 300
KYIV = "Kyiv City"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    tg_api_id: int | None = None
    tg_api_hash: SecretStr | None = None
    tg_session_path: Path = Path("~/.config/airalert/airalert.session")
    data_dir: Path = Path("data")
    reports_dir: Path = Path("reports")

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
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"


@lru_cache
def get_settings() -> Settings:
    return Settings()
