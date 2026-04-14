# -*- coding: utf-8 -*-
from pathlib import Path

path = Path(__file__).resolve().parent / "visit_card.py"
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
out: list[str] = []
i = 0
while i < len(lines):
    line = lines[i]
    if line.startswith("def vacancies_keyboard()"):
        out.append(line)
        i += 1
        out.append(lines[i])
        i += 1
        out.append(lines[i])
        i += 1
        while i < len(lines) and lines[i].strip() != "]":
            i += 1
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
        if i < len(lines):
            out.append(lines[i])
            i += 1
        while i < len(lines) and lines[i].strip() != ")":
            out.append(lines[i])
            i += 1
        if i < len(lines):
            out.append(lines[i])
            i += 1
        continue
    if line.startswith("def text_vacancies()"):
        out.append(line)
        i += 1
        out.append(lines[i])
        i += 1
        while i < len(lines) and lines[i].strip() != ")":
            i += 1
        body = (
            '        "\\U0001f4c2 *\\u041e\\u0442\\u043a\\u0440\\u044b\\u0442\\u044b\\u0435 \\u0432\\u0430\\u043a\\u0430\\u043d\\u0441\\u0438\\u0438*\\n\\n"\n'
            '        "\\U0001f539 *\\u0425\\u0435\\u043b\\u043f\\u0435\\u0440* \\u2014 \\u043d\\u0430\\u0432\\u0438\\u0433\\u0430\\u0446\\u0438\\u044f, \\u043f\\u043e\\u0434\\u0434\\u0435\\u0440\\u0436\\u043a\\u0430\\n\\n"\n'
            '        "\\U0001f539 *\\u0413\\u0440\\u0443\\u0437\\u0447\\u0438\\u043a* \\u2014 \\u043f\\u043e\\u0433\\u0440\\u0443\\u0437\\u043a\\u0430\\n\\n"\n'
            '        "\\U0001f539 *\\u041f\\u0440\\u043e\\u043c\\u043e\\u0443\\u0442\\u0435\\u0440* \\u2014 \\u043f\\u0440\\u0435\\u0437\\u0435\\u043d\\u0442\\u0430\\u0446\\u0438\\u044f\\n\\n"\n'
            '        "\\U0001f539 *\\u0413\\u0430\\u0440\\u0434\\u0435\\u0440\\u043e\\u0431\\u0449\\u0438\\u043a* \\u2014 \\u0433\\u0430\\u0440\\u0434\\u0435\\u0440\\u043e\\u0431\\n\\n"\n'
            '        "\\U0001f539 *\\u041f\\u0430\\u0440\\u043a\\u043e\\u0432\\u0449\\u0438\\u043a* \\u2014 \\u043f\\u0430\\u0440\\u043a\\u043e\\u0432\\u043a\\u0430\\n\\n"\n'
            '        "\\U0001f539 *\\u0425\\u043e\\u0441\\u0442\\u0435\\u0441* \\u2014 \\u0432\\u0441\\u0442\\u0440\\u0435\\u0447\\u0430 \\u0433\\u043e\\u0441\\u0442\\u0435\\u0439\\n\\n"\n'
            '        "\\U0001f539 *\\u0421\\u0443\\u043f\\u0435\\u0440\\u0432\\u0430\\u0439\\u0437\\u0435\\u0440* \\u2014 \\u043a\\u043e\\u043e\\u0440\\u0434\\u0438\\u043d\\u0430\\u0446\\u0438\\u044f"\n'
        )
        body = body.encode("utf-8").decode("unicode_escape")
        for bl in body.splitlines(keepends=True):
            out.append(bl)
        if i < len(lines):
            out.append(lines[i])
            i += 1
        continue
    out.append(line)
    i += 1

path.write_text("".join(out), encoding="utf-8")
print("vac ok")
