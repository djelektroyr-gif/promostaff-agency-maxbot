# -*- coding: utf-8 -*-
from pathlib import Path

path = Path(__file__).resolve().parent / "visit_card.py"
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
out: list[str] = []
for line in lines:
    if line.strip() == "tel = contact_phone_tel()":
        continue
    if 'f"tel:{tel}"' in line:
        out.append('        [cb_btn(f"Телефон: {CONTACT_PHONE}", "contact_show_phone")],\n')
        continue
    if "mailto:" in line and "CONTACT_EMAIL" in line:
        out.append('        [cb_btn(f"Email: {CONTACT_EMAIL}", "contact_show_email")],\n')
        out.append('        [cb_btn("Написать менеджеру", "ask_manager")],\n')
        continue
    if "contact_telegram_url()" in line and "Написать" in line:
        out.append('        [link_btn("WhatsApp", contact_whatsapp_url())],\n')
        out.append('        [link_btn("Telegram", contact_telegram_url())],\n')
        continue
    out.append(line)
path.write_text("".join(out), encoding="utf-8")
print("contact ok")
