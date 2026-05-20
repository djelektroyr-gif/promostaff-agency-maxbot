from __future__ import annotations

from unittest.mock import patch

import cabinet_web_login_token as tok


def test_build_link_requires_base_url():
    with patch.object(tok, "CABINET_WEB_BASE_URL", ""):
        url, err = tok.build_cabinet_web_login_url(10)
    assert url is None
    assert "не настроен адрес" in (err or "").lower()


def test_build_link_requires_http_scheme():
    with patch.object(tok, "CABINET_WEB_BASE_URL", "promostaff.local"):
        url, err = tok.build_cabinet_web_login_url(10)
    assert url is None
    assert "некорректно" in (err or "").lower()
