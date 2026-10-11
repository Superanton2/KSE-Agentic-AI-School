import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict[int, str]:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return {m["msg_id"]: m["text"] for m in data["messages"]}


@pytest.fixture(scope="session")
def official_msgs() -> dict[int, str]:
    return _load("air_alert_ua_sample.json")


@pytest.fixture(scope="session")
def etryvoga_msgs() -> dict[int, str]:
    return _load("etryvoga_sample.json")
