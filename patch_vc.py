# -*- coding: utf-8 -*-
"""Patch visit_card.py without embedding emojis in this script's source."""
from pathlib import Path

p = Path(__file__).resolve().parent / "visit_card.py"
lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
out: list[str] = []
i = 0
while i < len(lines):
    line = lines[i]
    if line.strip() == "tel = contact_phone_tel()":
        i += 1
        continue
    if "Позвонить:" in line and "tel:" in line and "CONTACT_PHONE" in line:
        out.append(
            '        [cb_btn(f"Телефон: {CONTACT_PHONE}", "contact_show_phone")],\n'
        )
        i += 1
        continue
    if "Написать в Telegram" in line and "link_btn" in line:
        out.append('        [link_btn("WhatsApp", contact_whatsapp_url())],\n')
        out.append(lines[i].replace("Написать в Telegram", "Telegram").replace("�� ", ""))
        i += 1
        continue
    if "mailto:" in line and "CONTACT_EMAIL" in line:
        out.append(
            '        [cb_btn(f"Email: {CONTACT_EMAIL}", "contact_show_email")],\n'
        )
        out.append('        [cb_btn("Написать менеджеру", "ask_manager")],\n')
        i += 1
        continue
    if "Отзывы" in line and "PORTFOLIO_URL" in line and "link_btn" in line:
        out.append(line.replace("link_btn", "cb_btn").split(", PORTFOLIO_URL")[0] + ', "reviews")],\n')
        i += 1
        continue
    if "Задать вопрос" in line and "ask_question" in line:
        out.append(line.replace("� Задать вопрос", "�� Частые вопросы").replace("ask_question", "faq"))
        i += 1
        continue
    if (
        "Как мы работаем" in line
        and i + 1 < len(lines)
        and "Отзывы" in lines[i + 1]
        and "PORTFOLIO_URL" in lines[i + 1]
    ):
        out.append(line)
        i += 1
        # skip old отзывы link row
        i += 1
        # insert calculate, join, site, reviews, faq order: next lines until contact_manager
        block = []
        while i < len(lines) and "Связаться с менеджером" not in lines[i]:
            block.append(lines[i])
            i += 1
        # reorder: want calculate, join_team, website, reviews, faq before manager
        reordered = []
        for bl in block:
            if "Заказать расчёт" in bl:
                reordered.append(bl)
            elif "Хочу в команду" in bl:
                reordered.append(bl)
            elif "Наш сайт" in bl:
                reordered.append(bl)
        reordered.append('        [cb_btn� Отзывы", "reviews")],\n')
        reordered.append('        [cb_btn("�� Частые вопросы", "faq")],\n')
        out.extend(reordered)
        continue
    if "Хочу на эту вакансию" in line:
        vac = [
            '            [cb_btn("Хочу: Хелпер", "vac_apply_helper")],\n',
            '            [cb_btn("Хочу: Грузчик", "vac_apply_loader")],\n',
            '            [cb_btn("Хочу: Промоутер", "vac_apply_promoter")],\n',
            '            [cb_btn("Хочу: Гардеробщик", "vac_apply_cloakroom")],\n',
            '            [cb_btn("Хочу: Парковщик", "vac_apply_parking")],\n',
            '            [cb_btn("Хочу: Хостес", "vac_apply_hostess")],\n',
            '            [cb_btn("Хочу: Супервайзер", "vac_apply_supervisor")],\n',
        ]
        out.extend(vac)
        i += 1
        continue
    out.append(line)
    i += 1

text = "".join(out)

if "def text_faq()" not in text:
    text = text.replace(
        "def message_main_menu()",
        '''def text_faq() -> str:
    return (
       � *Частые вопросы*\\n\\n"
        "*Сроки подбора?* Обычно 24–48 часов.\\n\\n"
        "*География?* Работаем в разных городах.\\n\\n"
        "*Стоимость?* Индивидуально, детали в КП.\\n\\n"
        "*Связь?* «Заказать расчёт» или «Связаться с менеджером»."
    )


def text_reviews() -> str:
    return (
        "�� *Отзывы*\\n\\n"
        "Клиенты отмечают пунктуальность и понятную коммуникацию. Много повторных проектов."
    )


def message_main_menu()''',
    )

# text_vacancies: strip rates lines (simplified)
if "от 6 000" in text:
    text = text.replace(
        '"� *Открытые вакансии и ставки*\\n\\n"',
        '"�� *Открытые вакансии*\\n\\n"',
    )
    import re as _re

    text = _re.sub(r"�� \*[^*]+\* — от [0-9 ,]+�/смена\\n", "", text)

p.write_text(text, encoding="utf-8")
print("patched")
