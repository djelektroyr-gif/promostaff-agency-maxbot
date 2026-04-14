# -*- coding: utf-8 -*-
from pathlib import Path

path = Path(__file__).resolve().parent / "visit_card.py"
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
out: list[str] = []
i = 0
while i < len(lines):
    line = lines[i]
    if line.startswith("from config import ("):
        out.append(line)
        i += 1
        while i < len(lines) and lines[i].strip() != ")":
            if "PORTFOLIO_URL" not in "".join(out[-5:]) and "CONTACT_TELEGRAM" in lines[i]:
                out.append(lines[i])
                out.append("    PORTFOLIO_URL,\n")
                i += 1
                continue
            out.append(lines[i])
            i += 1
        out.append(lines[i])
        i += 1
        continue
    out.append(line)
    i += 1

text = "".join(out)
# main menu: drop PORTFOLIO отзывы row, reorder
text = text.replace(
    '        [link_btn("�� Отзывы", PORTFOLIO_URL)],\n        [cb_btn("�� Заказать расчёт", "calculate")],\n        [link_btn("��� Наш сайт", WEBSITE_URL)],\n        [� Задать вопрос", "ask_question")],\n        [cb_btn("�� Хочу в команду", "join_team")],',
    '        [cb_btn("�� Заказать расчёт", "calculate")],\n        [cb_btn("�� Хочу в команду", "join_team")],\n        [link_btn("��� Наш сайт", WEBSITE_URL)],\n        [cb_btn("�� Отзывы", "reviews")],\n        [cb� Частые вопросы", "faq")],',
)
text = text.replace(
    '        [link_btn("�� Отзывы клиентов", PORTFOLIO_URL)],',
    '        [cb_btn("�� Отзывы", "reviews")],',
)
text = text.replace(
    '        [link_btn("�� Отзывы", PORTFOLIO_URL)],',
    '        [cb_btn("�� Отзывы", "reviews")],',
)

old_c = '''def contact_keyboard() -> list[dict]:
    tel = contact_phone_tel()
    rows: list[list[dict]] = [
        [link_btn(f"�� Позвонить: {CONTACT_PHONE}", f"tel:{tel}")],
        [� Написать в Telegram", contact_telegram_url())],
        [link_btn(f"�� {CONTACT_EMAIL}", f"mailto:{CONTACT_EMAIL}")],
        [cb_btn("�� В главное меню", "main_menu")],
    ]
    return inline_keyboard(rows)'''

new_c = '''def contact_keyboard() -> list[dict]:
    rows: list[list[dict]] = [
        [cb_btn(f"�� Телефон: {CONTACT_PHONE}", "contact_show_phone")],
        [link_btn("WhatsApp", contact_whatsapp_url())],
        [link_btn("Telegram", contact_telegram_url())],
        [cb� Email: {CONTACT_EMAIL}", "contact_show_email")],
        [� Написать менеджеру", "ask_manager")],
        [� В главное меню", "main_menu")],
    ]
    return inline_keyboard(rows)'''

if old_c in text:
    text = text.replace(old_c, new_c)

old_v = '''def vacancies_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("��� Хочу на эту вакансию", "fill_anketa")],
            [cb_btn("���️ Назад", "join_team")],
            [cb_btn("�� В главное меню", "main_menu")],
        ]
    )'''

new_v = '''def vacancies_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("Хочу: Хелпер", "vac_apply_helper")],
            [cb_btn("Хочу: Грузчик", "vac_apply_loader")],
            [cb_btn("Хочу: Промоутер", "vac_apply_promoter")],
            [cb_btn("Хочу: Гардеробщик", "vac_apply_cloakroom")],
            [cb_btn("Хочу: Парковщик", "vac_apply_parking")],
            [cb_btn("Хочу: Хостес", "vac_apply_hostess")],
            [cb_btn("Хочу: Супервайзер", "vac_apply_supervisor")],
            [cb�️ Назад", "join_team")],
            [cb_btn("�� В главное меню", "main_menu")],
        ]
    )'''

if old_v in text:
    text = text.replace(old_v, new_v)

old_tv_start = 'def text_vacancies() -> str:\n    return (\n        "�� *Открытые вакансии и ставки*\\n\\n"'
if old_tv_start in text:
    idx = text.index(old_tv_start)
    idx2 = text.index("    )\n\n\ndef message_main_menu", idx)
    text = (
        text[:idx]
        + "def text_vacancies() -> str:\n"
        + "    return (\n"
        + '        "�� *Открытые вакансии*\\n\\n"\n'
        + '        "�� *Хелпер* — навигация, поддержка\\n\\n"\n'
        + '        "�� *Грузчик* — погрузка и перенос\\n\\n"\n'
        + '        "�� *Промоутер* — презентация продукта\\n\\n"\n'
        +� *Гардеробщик* — гардероб\\n\\n"\n'
        + '        "�� *Парковщик* — парковка\\n\\n"\n'
        +� *Хостес* — встреча гостей\\n\\n"\n'
        +� *Супервайзер* — координация"\n'
        + "    )\n\n"
        + "def text_faq() -> str:\n"
        + "    return (\n"
        + '        "�� *Частые вопросы*\\n\\n"\n'
        + '        "*Сроки подбора?* Обычно 24–48 часов.\\n\\n"\n'
        + '        "*География?* Работаем в разных городах.\\n\\n"\n'
        + '        "*Стоимость?* Индивидуально, детали в КП.\\n\\n"\n'
        + '        "*Связь?* «Заказать расчёт» или «Связаться с менеджером»."\n'
        + "    )\n\n"
        + "def text_reviews() -> str:\n"
        + "    return (\n"
        + '        "�� *Отзывы*\\n\\n"\n'
        + '        "Клиенты отмечают пунктуальность и понятную коммуникацию. Много повторных проектов."\n'
        + "    )\n\n"
        + text[idx2:]
    )

path.write_text(text, encoding="utf-8")
print("done")
