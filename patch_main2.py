# -*- coding: utf-8 -*-
from pathlib import Path

INNER = """        [cb_btn("\\U0001f4cb \\u041e PROMOSTAFF AGENCY", "about")],
        [cb_btn("\\u2b50 \\u041f\\u0440\\u0435\\u0438\\u043c\\u0443\\u0449\\u0435\\u0441\\u0442\\u0432\\u0430", "advantages")],
        [cb_btn("\\U0001f504 \\u041a\\u0430\\u043a \\u043c\\u044b \\u0440\\u0430\\u0431\\u043e\\u0442\\u0430\\u0435\\u043c", "how_we_work")],
        [cb_btn("\\U0001f4b0 \\u0417\\u0430\\u043a\\u0430\\u0437\\u0430\\u0442\\u044c \\u0440\\u0430\\u0441\\u0447\\u0451\\u0442", "calculate")],
        [cb_btn("\\U0001f465 \\u0425\\u043e\\u0447\\u0443 \\u0432 \\u043a\\u043e\\u043c\\u0430\\u043d\\u0434\\u0443", "join_team")],
        [link_btn("\\U0001f310 \\u041d\\u0430\\u0448 \\u0441\\u0430\\u0439\\u0442", WEBSITE_URL)],
        [cb_btn("\\U0001f4ac \\u041e\\u0442\\u0437\\u044b\\u0432\\u044b", "reviews")],
        [cb_btn("\\u2753 \\u0427\\u0430\\u0441\\u0442\\u044b\\u0435 \\u0432\\u043e\\u043f\\u0440\\u043e\\u0441\\u044b", "faq")],
        [cb_btn("\\U0001f4de \\u0421\\u0432\\u044f\\u0437\\u0430\\u0442\\u044c\\u0441\\u044f \\u0441 \\u043c\\u0435\\u043d\\u0435\\u0434\\u0436\\u0435\\u0440\\u043e\\u043c", "contact_manager")],
"""
INNER = INNER.encode("utf-8").decode("unicode_escape")

path = Path(__file__).resolve().parent / "visit_card.py"
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
s = next(i for i, l in enumerate(lines) if "rows: list[list[dict]]" in l)
e = next(i for i in range(s + 1, len(lines)) if lines[i].strip() == "]")
new_inner = [x + "\n" for x in INNER.splitlines()]
lines = lines[: s + 1] + new_inner + lines[e:]
path.write_text("".join(lines), encoding="utf-8")

# advantages + about: replace link отзывы
text = path.read_text(encoding="utf-8")
text = text.replace(
    '[link_btn("\\U0001f4ac \\u041e\\u0442\\u0437\\u044b\\u0432\\u044b \\u043a\\u043b\\u0438\\u0435\\u043d\\u0442\\u043e\\u0432", PORTFOLIO_URL)],'.encode(
        "utf-8"
    ).decode("unicode_escape"),
    '[cb_btn("\\U0001f4ac \\u041e\\u0442\\u0437\\u044b\\u0432\\u044b", "reviews")],'.encode("utf-8").decode(
        "unicode_escape"
    ),
)
text = text.replace(
    '[link_btn("\\U0001f4ac \\u041e\\u0442\\u0437\\u044b\\u0432\\u044b", PORTFOLIO_URL)],'.encode("utf-8").decode(
        "unicode_escape"
    ),
    '[cb_btn("\\U0001f4ac \\u041e\\u0442\\u0437\\u044b\\u0432\\u044b", "reviews")],'.encode("utf-8").decode(
        "unicode_escape"
    ),
)
path.write_text(text, encoding="utf-8")
print("ok")
