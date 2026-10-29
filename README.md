# StreamToOffline

Скачивай отдельные треки и Spotify-плейлисты через локальный Exportify + Soulseek (Sockseek) с честным YouTube-fallback. Музыка раскладывается в удобную библиотеку с тегами и жанровыми папками.

## Быстрый старт

1. Открой папку проекта (например, `D:\StreamToOffline`).
2. Запусти TUI-мастер:
   - **Windows:** `Start.bat`
   - **Linux/macOS:** `./start.sh`
3. Выбери источник, профиль качества и папку назначения клавишами или мышью.
4. Музыка сохраняется в `library` внутри папки проекта.

## Меню

```
1. Download a single song
2. Download a Spotify playlist
3. Download from Exportify CSV
4. Retry an unfinished job
5. Check tools (doctor)
0. Exit
```

Интерфейс работает в терминале как TUI: используй Tab/стрелки для навигации и Enter для выбора. Клавиша `q` закрывает приложение.
Ошибочный ввод показывается отдельным окном, длительные операции выполняются в фоне.

## Источники

### 1. Одна песня

- Введи `Artist - Title` — скачается именно этот трек.
- Или введи произвольный поисковый запрос — программа найдёт похожие треки в Soulseek и предложит выбрать номера.

### 2. Spotify-плейлист

- Вставь ссылку на плейлист.
- Откроется локальный Exportify: войди в Spotify. После входа указанный плейлист автоматически отправится в приложение.
- CSV не сохраняется на диск — треки передаются прямо в программу.

### 3. CSV из Exportify

- Выбери, нужно ли сначала экспортировать плейлист из Exportify.
- Или укажи путь к готовому CSV.

### 4. Retry

- Показывает список незавершённых заданий: ID, название, статус, прогресс.
- Выбери номер — программа докачает недостающие треки.

## Профили качества

| Профиль | Описание |
|---|---|
| `kia` | MP3 320 kbps, 44.1 kHz, без обложек — для Kia Ceed 1 FL |
| `lossless` | FLAC/WAV |
| `auto` | выбирает лучшее из Soulseek |
| `custom` | вручную: формат, битрейт, частота дискретизации, версия трека |

## Сортировка

- При включённой сортировке программа анализирует жанры и настроение плейлиста и создаёт только те папки, которые реально нужны (Metal, Rock, Hip-Hop, Electronic, Pop, R&B/Soul, Drive, Chill, Melancholy и др.).
- Пустые или неподходящие категории не создаются.

## Fallback

- Основной источник — **Soulseek**.
- Если у трека нет подходящих кандидатов, а YouTube-fallback включён, программа попробует скачать с YouTube.
- В логе видно, почему Soulseek-вариант отброшен: неправильное качество, длительность или версия.

## Проверка инструментов

```powershell
# Windows
.\.venv\Scripts\streamtooffline.exe doctor

# Linux/macOS
.venv/bin/streamtooffline doctor
```

Если FFmpeg отсутствует, на Windows можно установить автоматически:

```powershell
.\.venv\Scripts\streamtooffline.exe doctor --install-ffmpeg
```

Sockseek is an external executable, not a PyPI package. On Windows install the
pinned release into `.tools/bin` with:

```powershell
.\.venv\Scripts\streamtooffline.exe doctor --install-sockseek
```

The installer verifies the archive checksum. On Linux/macOS, download the
matching Sockseek release and set `SOCKSEEK_PATH` to its executable.

To automatically install/fix all repository-managed tools (FFmpeg, Sockseek,
yt-dlp, pnpm and Exportify), run:

```powershell
.\.venv\Scripts\streamtooffline.exe doctor --fix
```

The TUI button **Check / fix tools** runs the same repair flow.

На Linux/macOS `doctor` подскажет команду пакетного менеджера (`apt install ffmpeg` / `brew install ffmpeg`).

## Запуск из командной строки

Примеры для Windows (на Linux/macOS замени `.\.venv\Scripts\streamtooffline.exe` на `.venv/bin/streamtooffline`):

```powershell
# Мастер
.\.venv\Scripts\streamtooffline.exe wizard

# Одна песня
.\.venv\Scripts\streamtooffline.exe song "АК-47 - В тепле 2 яйца" --profile kia

# Плейлист
.\.venv\Scripts\streamtooffline.exe playlist "https://open.spotify.com/playlist/..." --profile kia --youtube-fallback

# CSV
.\.venv\Scripts\streamtooffline.exe csv "D:\Music\Big_Playlist.csv" --profile kia

# Retry
.\.venv\Scripts\streamtooffline.exe retry JOB_ID --yes
```

## Переменные окружения

- `SOULSEEK_USERNAME` / `SOULSEEK_PASSWORD` — логин/пароль Soulseek.
- `HTTPS_PROXY` / `HTTP_PROXY` — необязательный proxy для YouTube-fallback при проблемах TLS/доступа к YouTube.
- `PYTHONUNBUFFERED=1` — вывод в консоль без буферизации (устанавливается в `Start.bat` / `start.sh`).

## Структура проекта

```
StreamToOffline
├── Start.bat                  # запуск мастера (Windows)
├── start.sh                   # запуск мастера (Linux/macOS)
├── config/
│   ├── artists.yml            # маппинг русских имён
│   ├── genres.yml             # жёсткие жанровые правила
│   └── adaptive.yml           # адаптивные жанровые категории
├── src/streamtooffline/
│   ├── cli.py                 # командный интерфейс
│   ├── wizard.py              # консольный мастер
│   ├── application/           # orchestration: download, search
│   ├── domain/                # модели, планировщик, библиотека
│   └── infrastructure/        # адаптеры: Soulseek, FFmpeg, YouTube, Exportify, теги
├── tests/                     # pytest
└── .tools/                    # изолированные инструменты
    ├── bin/
    │   ├── sockseek(.exe)
    │   └── ffmpeg(.exe)
    ├── exportify/             # локальный Exportify
    └── pnpm/
```

## Разработка

```powershell
# Установить зависимости (Linux/macOS: .venv/bin/python)
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

# Запустить тесты
.\.venv\Scripts\python.exe -m pytest -q
```
