Логотип агентства (PNG)
=======================

1. Положите файл в репозиторий:  assets/logo.png  (как в Telegram-визитке — один и тот же арт).

2. MAX Platform API отправляет изображения по публичному HTTPS-URL, а не из локального пути.
   После того как тот же PNG доступен в интернете (например https://promostaff-agency.ru/logo.png ),
   на сервере MAX в .env укажите:
   BRAND_LOGO_URL=https://...

   Тогда в приветствии появится ссылка «Логотип» на этот URL.

3. Коммит файла в git (чтобы не потерять исходник):
   git add assets/logo.png
   git commit -m "Add agency logo asset"
   git push
