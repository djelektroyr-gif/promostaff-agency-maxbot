# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(__file__).resolve().parent / "visit_card.py"
t = p.read_text(encoding="utf-8")
old = """    rows: list[list[dict]] = [
        [cb_btn("�� О PROMOSTAFF AGENCY", "about")],
        [cb_btn("⭐ Преимущества", "advantages")],
        [cb_btn("��� Как мы работаем", "how_we_work")],
        [link_btn("�� Отзывы", PORTFOLIO_URL)],
        [cb_btn("�� Заказать расчёт", "calculate")],
        [link_btn("��� Наш сайт", WEBSITE_URL)],
        [cb_btn("�� Задать вопрос", "ask_question")],
        [cb_btn("�� Хочу в команду", "join_team")],
        [� Связаться с менеджером", "contact_manager")],
    ]"""
new = """    rows: list[list[dict]] = [
        [cb_btn("�� О PROMOSTAFF AGENCY", "about")],
        [cb_btn("⭐ Преимущества", "advantages")],
        [cb_btn("��� Как мы работаем", "how_we_work")],
        [cb_btn("�� Заказать расчёт", "calculate")],
        [cb_btn("�� Хочу в команду", "join_team")],
        [link_btn("��� Наш сайт", WEBSITE_URL)],
        [cb_btn("�� Отзывы", "reviews")],
        [cb_btn("�� Частые вопросы", "faq")],
        [� Связаться с менеджером", "contact_manager")],
    ]"""
if old not in t:
    raise SystemExit("main_menu block not found")
t = t.replace(old, new)
t = t.replace(
    '[link_btn("�� Отзывы клиентов", PORTFOLIO_URL)],',
    '[cb_btn("�� Отзывы", "reviews")],',
)
t = t.replace(
    '[link_btn("�� Отзывы", PORTFOLIO_URL)],',
    '[cb_btn("�� Отзывы", "reviews")],',
)
old_v = """def vacancies_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("��� Хочу на эту вакансию", "fill_anketa")],
            [��️ Назад", "join_team")],
            [cb_btn("�� В главное меню", "main_menu")],
        ]
    )"""
new_v = """def vacancies_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("Хочу: Хелпер", "vac_apply_helper")],
            [cb_btn("Хочу: Грузчик", "vac_apply_loader")],
            [cb_btn("Хочу: Промоутер", "vac_apply_promoter")],
            [cb_btn("Хочу: Гардеробщик", "vac_apply_cloakroom")],
            [cb_btn("Хочу: Парковщик", "vac_apply_parking")],
            [cb_btn("Хочу: Хостес", "vac_apply_hostess")],
            [cb_btn("Хочу: Супервайзер", "vac_apply_supervisor")],
            [cb_btn("���️ Назад", "join_team")],
            [cb_btn("�� В главное меню", "main_menu")],
        ]
    )"""
if old_v in t:
    t = t.replace(old_v, new_v)
else:
    print("vacancies_keyboard skip")
old_tv = """       � *Хелпер* — от 6 000 ��/смена\\n"
        "Навигация, логистика, поддержка\\n\\n"
        "�� *Гардеробщик* — от �/смена\\n"
        "Обслуживание гардероба, учёт вещей\\n\\n"
        "�� *Парковщик* — от 7 500 ��/смена\\n"
        "Организация парковки, управление потоками\\n\\n"
        "�� *Промоутер* — от 7 500 ��/смена\\n"
        "Презентация продуктов, раздача материалов\\n\\n� *Хостес* — от 8 000 ��/смена\\n"
        "Работа с гостями, регистрация\\n\\n� *Супервайзер* — от �/смена\\n"
        "Координация команды, контроль\""""
new_tv =� *Хелпер* — навигация, поддержка\\n\\n"
        "�� *Грузчик* — погрузка и перенос\\n\\n"
        "�� *Промоутер* — презентация продукта\\n\\n"
        "�� *Гардеробщик* — гардероб\\n\\n"
        "�� *Парковщик* — парковка\\n\\n"
        "�� *Хостес* — встреча гостей\\n\\n"
        "�� *Супервайзер* — координация на площадке\""""
if old_tv in t:
    t = t.replace(
        '"�� *Открытые вакансии и ставки*\\n\\n"',
        '"�� *Открытые вакансии*\\n\\n"',
    )
    t = t.replace(old_tv, new_tv)
else:
    print("text_vacancies skip")

p.write_text(t, encoding="utf-8")
print("main ok")
