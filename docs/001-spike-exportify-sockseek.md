# Spike 001: Exportify + Sockseek

Дата: 2026-10-28.

## Проверено

### Exportify

- Источник: `watsonbox/exportify`, закреплён commit `d8eaeb92e7911a2bb626bdcb9d378b0cfe086c12`.
- Зависимости установлены изолированно в `.tools`, пакетный менеджер `pnpm@10.34.5` из `package.json`.
- Команда запуска: `pnpm start -- --host 127.0.0.1 --port 3000 --strictPort`.
- Адрес OAuth callback: `http://127.0.0.1:3000` (именно `127.0.0.1`, не `localhost`).
- Это браузерное OAuth-приложение; пароль Spotify ядру не нужен.

### Sockseek JSON

Выполнен реальный поиск одного трека с `--print-json`. Результат — JSON-массив; подтверждены поля:

- `User.Username`, `User.UploadSpeed`, `User.HasFreeUploadSlot`;
- `File.Filename`, `File.Length` (секунды), `File.Size` (байты), `File.Bitrate`.

Пример сохранён в `artifacts/sockseek-search.json`. Этого достаточно для оценки кандидатов, точного размера и выбора раздачи без парсинга человекочитаемой таблицы.

## Осталось для закрытия spike

Интерактивный OAuth не потребовался повторять: по решению в текущей сессии принят ранее экспортированный `D:\Music\Big_Playlist.csv` (3200 треков) как подтверждение рабочего Exportify→CSV. Локальный Exportify при этом запущен и возвращает HTTP 200.

## Решение

Архитектура жизнеспособна: локальный Exportify + один ручной браузерный вход + автоматический подхват CSV; Sockseek использовать как subprocess с JSON-контрактом и закреплённой версией.
