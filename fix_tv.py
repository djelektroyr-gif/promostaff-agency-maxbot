# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(__file__).resolve().parent / "visit_card.py"
lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
s = next(i for i, l in enumerate(lines) if l.startswith("def text_vacancies"))
e = next(i for i in range(s + 1, len(lines)) if lines[i].startswith("def text_faq"))
new_fn = [
    "def text_vacancies() -> str:\n",
    "    return (\n",
    '        "\U0001f4c2 *\u041e\u0442\u043a\u0440\u044b\u0442\u044b\u0435 \u0432\u0430\u043a\u0430\u043d\u0441\u0438\u0438*\\n\\n"\n',
    '        "\U0001f539 *\u0425\u0435\u043b\u043f\u0435\u0440* \u2014 \u043d\u0430\u0432\u0438\u0433\u0430\u0446\u0438\u044f, \u043f\u043e\u0434\u0434\u0435\u0440\u0436\u043a\u0430 \u0433\u043e\u0441\u0442\u0435\u0439\\n\\n"\n',
    '        "\U0001f539 *\u0413\u0440\u0443\u0437\u0447\u0438\u043a* \u2014 \u043f\u043e\u0433\u0440\u0443\u0437\u043a\u0430, \u043f\u0435\u0440\u0435\u043d\u043e\u0441\\n\\n"\n',
    '        "\U0001f539 *\u041f\u0440\u043e\u043c\u043e\u0443\u0442\u0435\u0440* \u2014 \u043f\u0440\u0435\u0437\u0435\u043d\u0442\u0430\u0446\u0438\u044f\\n\\n"\n',
    '        "\U0001f539 *\u0413\u0430\u0440\u0434\u0435\u0440\u043e\u0431\u0449\u0438\u043a* \u2014 \u0433\u0430\u0440\u0434\u0435\u0440\u043e\u0431\\n\\n"\n',
    '        "\U0001f539 *\u041f\u0430\u0440\u043a\u043e\u0432\u0449\u0438\u043a* \u2014 \u043f\u0430\u0440\u043a\u043e\u0432\u043a\u0430\\n\\n"\n',
    '        "\U0001f539 *\u0425\u043e\u0441\u0442\u0435\u0441* \u2014 \u0432\u0441\u0442\u0440\u0435\u0447\u0430 \u0433\u043e\u0441\u0442\u0435\u0439, \u0440\u0435\u0433\u0438\u0441\u0442\u0440\u0430\u0446\u0438\u044f\\n\\n"\n',
    '        "\U0001f539 *\u0421\u0443\u043f\u0435\u0440\u0432\u0430\u0439\u0437\u0435\u0440* \u2014 \u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0446\u0438\u044f \u043d\u0430 \u043f\u043b\u043e\u0449\u0430\u0434\u043a\u0435"\n',
    "    )\n",
    "\n",
]
lines = lines[:s] + new_fn + lines[e:]
p.write_text("".join(lines), encoding="utf-8")
print("text_vacancies fixed")
