"""Telethon client factory. The collector is strictly read-only: it only resolves public channels and
reads their history/updates; it never sends, joins or modifies anything."""

import os
from pathlib import Path

from telethon import TelegramClient

from airalert.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
# Telethon sleeps by itself on FloodWait shorter than this; longer waits raise and are handled by callers.
FLOOD_SLEEP_THRESHOLD = 24 * 3600


def session_file(path: Path) -> Path:
    """Telethon appends '.session' when the name lacks it."""
    return path if path.suffix == ".session" else path.with_name(path.name + ".session")


def check_session_location(path: Path) -> None:
    if (REPO_ROOT / ".git").exists() and path.is_relative_to(REPO_ROOT):
        raise RuntimeError(
            f"TG_SESSION_PATH must be outside the repository ({REPO_ROOT}); the session grants full access "
            "to the Telegram account."
        )


def secure_session(path: Path) -> None:
    f = session_file(path)
    if f.exists():
        os.chmod(f, 0o600)


def make_client(s: Settings) -> TelegramClient:
    if s.tg_api_id is None or s.tg_api_hash is None:
        raise RuntimeError("TG_API_ID / TG_API_HASH are not set (see .env.example)")
    path = s.session_path
    check_session_location(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    return TelegramClient(
        str(path),
        s.tg_api_id,
        s.tg_api_hash.get_secret_value(),
        flood_sleep_threshold=FLOOD_SLEEP_THRESHOLD,
        receive_updates=True,
    )


# Human-readable "where did the code go" for auth.SentCode.type (no phone number is ever printed).
_CODE_DESTINATION = {
    "SentCodeTypeApp": "у застосунок Telegram — службовий чат «Telegram» (синя галочка) на іншому вашому пристрої",
    "SentCodeTypeSms": "SMS",
    "SentCodeTypeSmsWord": "SMS (слово)",
    "SentCodeTypeSmsPhrase": "SMS (фраза)",
    "SentCodeTypeFirebaseSms": "SMS",
    "SentCodeTypeCall": "дзвінком (код продиктують)",
    "SentCodeTypeFlashCall": "flash-дзвінком (код — останні цифри номера, що дзвонив)",
    "SentCodeTypeMissedCall": "пропущеним дзвінком (код — останні цифри номера, що дзвонив)",
    "SentCodeTypeEmailCode": "на email, прив'язаний до акаунта",
    "SentCodeTypeFragmentSms": "у Fragment (fragment.com), бо номер анонімний",
    "SentCodeTypeSetUpEmailRequired": "нікуди: Telegram вимагає спершу прив'язати email у застосунку",
}


def describe_sent_code(sent) -> str:
    kind = type(sent.type).__name__
    where = _CODE_DESTINATION.get(kind, kind)
    nxt = type(sent.next_type).__name__ if getattr(sent, "next_type", None) else None
    extra = f"; повторний запит піде як {_CODE_DESTINATION.get(nxt, nxt)}" if nxt else ""
    timeout = f" (не раніше ніж через {sent.timeout} с)" if getattr(sent, "timeout", None) else ""
    return f"Код надіслано {where}{extra}{timeout}."


async def _password(client: TelegramClient, ask_password) -> None:
    await client.sign_in(password=ask_password())


async def login_qr(client: TelegramClient, show, ask_password, attempts: int = 5) -> None:
    """Scan with Telegram on the phone: Settings → Devices → Link Desktop Device."""
    from telethon.errors import SessionPasswordNeededError

    qr = await client.qr_login()
    for _ in range(attempts):
        show(qr.url)
        try:
            await qr.wait(timeout=60)
            return
        except TimeoutError:
            await qr.recreate()
        except SessionPasswordNeededError:
            await _password(client, ask_password)
            return
    raise RuntimeError("QR не відскановано — спробуйте ще раз")


async def login_code(client: TelegramClient, ask, ask_password, echo) -> None:
    from telethon.errors import SessionPasswordNeededError

    phone = ask("Телефон у форматі +380…")
    sent = await client.send_code_request(phone)
    echo(describe_sent_code(sent))
    code = ask("Код (Enter без коду — запросити повторно іншим способом)")
    if not code:
        sent = await client.send_code_request(phone)
        echo(describe_sent_code(sent))
        code = ask("Код")
    try:
        await client.sign_in(phone, code, phone_code_hash=sent.phone_code_hash)
    except SessionPasswordNeededError:
        await _password(client, ask_password)
