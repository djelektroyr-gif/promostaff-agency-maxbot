# agency_pro_vendor.py — код PROMOSTAFF PRO из vendor/promostaff-bot (без путей в .env).
# Ожидается: promostaff-agency-maxbot/vendor/promostaff-bot/ (submodule или копия).
from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_AGENCY_ROOT = Path(__file__).resolve().parent
VENDOR_PROMOSTAFF_BOT = _AGENCY_ROOT / "vendor" / "promostaff-bot"


def vendor_promostaff_bot_ready() -> bool:
    return VENDOR_PROMOSTAFF_BOT.is_dir() and (
        VENDOR_PROMOSTAFF_BOT / "max_webhook" / "max_bot.py"
    ).is_file()


def ensure_promostaff_vendor_path() -> bool:
    if not vendor_promostaff_bot_ready():
        return False
    root = str(VENDOR_PROMOSTAFF_BOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    return True


def vendor_help_message() -> str:
    return (
        "Регистрация исполнителя как в PROMOSTAFF PRO подключается из "
        f"`{VENDOR_PROMOSTAFF_BOT.relative_to(_AGENCY_ROOT)}`. "
        "Добавьте submodule или скопируйте репозиторий promostaff-bot — см. vendor/README.md."
    )
