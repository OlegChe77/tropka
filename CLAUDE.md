# Тропка (Tropka)

Программа для Windows: файлы и текст между ПК и телефоном по домашней сети. ПК поднимает HTTPS-сервер, показывает QR с PIN; телефон открывает страницу в обычном браузере (ничего не ставит). Свой продукт, не клон LocalSend. Интерфейс на русском, отвечать пользователю просто и коротко.

Стек: Python 3.12, aiohttp, cryptography (сертификат), qrcode, PySide6 (окно), pystray (трей), SQLite, PyInstaller (один .exe).

## План
1. ✅ Сервер, QR, PIN, приём файла с телефона.
2. ✅ Скачивание с ПК на телефон, очередь «на телефон», текст в обе стороны, общая лента.
3. ✅ Окно «Лента» (шапка с телефоном/статусом/QR, лента, скрепка, поле, «Буфер», отправка; тема по Windows) и значок в трее.
4. ✅ Сборка в один exe (`build.ps1`), проверка на 127.0.0.1. Ждёт ручной проверки с настоящими телефонами.

Переименовано из «Мост»/Most в «Тропка»/Tropka (2026-11-02); пакет остался `most/`.

Репозиторий https://github.com/OlegChe77/tropka (ветка main; `gh` — `C:\Users\user\tools\gh\bin\gh.exe`). `README.md` со скриншотами `docs/window.png`, `docs/qr.png` (делаются через `win.grab()`, имя ПК подменять `config.pc_name`). Соседний «Тропка Онлайн» (`..\Tropka Online`, телефон↔телефон) в README — только ссылкой на сайт.

Потом: общий буфер, «Отправить на телефон» в проводнике, автосортировка, сгорающие ссылки. Отдельный проект: телефон↔телефон через WebRTC.

## Файлы
- `most/__main__.py` — запуск: по умолчанию окно (`gui.run`), `--console` — консоль (QR в терминале + `%APPDATA%\Tropka\qr.png`, строка: путь → файл, иначе текст). Файлы-аргументы уходят на телефон.
- `most/service.py` — `BridgeService`: Store + Events + Bridge, сервер в своём потоке с asyncio-циклом; `start()` ждёт запуска, `stop()`; `ips` — адреса для QR.
- `most/gui/__init__.py` — `run()`: QApplication, один экземпляр (QLocalServer `tropka-<user>`: второй запуск передаёт файлы первому и выходит), трей, тема.
- `most/gui/window.py` — `MainWindow` (шапка, лента, поле, перетаскивание, «Буфер»: файлы/картинка/текст), `QrDialog` (QR, PIN, «Новый PIN»), `EventRelay` (события → Qt-сигнал).
- `most/gui/feed.py` — `FeedView`, пузыри `TextBubble`/`FileBubble` (ход передачи, «Открыть», «Показать в папке», «Копировать»), разделители дат.
- `most/gui/theme.py` — цвета светлой/тёмной темы, QSS, значки Segoe MDL2 Assets. `MOST_THEME=dark|light` — принудительно.
- `most/sounds.py` — звуки ПК (winsound, `most/sounds/*.wav`: online/file/text/delivered), вкл/выкл в `%APPDATA%\Tropka\settings.json`; кнопка-динамик в шапке окна. WAV делает `packaging/make_sounds.py`.
- `most/gui/tray.py` — значок в трее (pystray, свой поток): «Открыть», «Показать QR», «Помощь проекту», «Выход»; картинка значка (PIL).
- `most/server.py` — `Bridge`: PIN, сессии-cookie, API (`/api/upload` PUT, `/api/text`, `/api/feed`, `/api/clear` POST, `/api/events` SSE, `/api/file/{id}`, `?view=1` — «Открыть» в браузере), `offer_file/offer_text/clear_feed` (из любого потока), `online_devices()`.
- `most/certs.py` — самоподписанный сертификат (EC P-256, SAN с IP ПК).
- `most/store.py` — SQLite: `devices` (хэш токена), `history` (лента: in — с телефона, out — с ПК), `deliveries` (кто что забрал), `meta` (`history_floor`); `pending_for` — очередь «на телефон»; `clear_history`.
- `most/events.py` — шина событий (`device_joined/online/offline`, `upload_*`, `file_received`, `text_received`, `file_offered`, `text_offered`, `delivered`, `feed_cleared`).
- `most/config.py` — пути, `APP_NAME`: данные `%APPDATA%\Tropka` (старый `%APPDATA%\Most` переносится при первом запуске, если новой папки нет), принятые файлы «Загрузки\Tropka».
- `most/netutil.py` — IP в локальной сети.
- `most/firewall.py` — пустит ли Windows телефон: правило брандмауэра для exe (`netsh … show rule`, без админа), общедоступная ли сеть (PowerShell `Get-NetConnectionProfile`); `fix()` — одним UAC удаляет старые правила exe и правило старого имени «Мост», добавляет разрешающее (частная+домен) и делает сеть частной. В exe проверка при запуске (`MainWindow.check_network`): вопрос «Разрешить» + предупреждение и кнопка в окне QR.
- `most/web/` — страница телефона (index.html, style.css, app.js), без внешних библиотек. Звуки — Web Audio (синтез), кнопка-динамик, выбор в `localStorage`.
- `tests/test_server.py` — тесты (unittest, без сети).
- `build.ps1` — сборка `dist\Tropka.exe`; `packaging/most.spec` (что кладём/выкидываем), `packaging/launcher.py` (точка входа), `packaging/make_assets.py` (значок .ico из `tray.icon_image`, свойства файла из `most.__version__` → `build/`).
- `PHONE_TEST.md` — инструкция для ручной проверки exe с Android/iPhone.

## Команды
```
python -m most                      # окно + трей (порт 47321, HTTPS)
python -m most --console            # консольный режим
python -m most --hidden             # сразу в трей
python -m most --host 127.0.0.1 --no-tls --port N   # отладка без брандмауэра и HTTPS
python -m unittest discover tests   # тесты
powershell -ExecutionPolicy Bypass -File build.ps1   # → dist\Tropka.exe (~41 МБ, ~1 мин)
dist\Tropka.exe --host 127.0.0.1 --port 47398          # проверка exe: curl.exe -sk https://127.0.0.1:47398/
```
Версия exe — `__version__` в `most/__init__.py`.

## Подводные камни
- Сертификат самоподписанный: телефон один раз предупредит (Chrome помнит исключение ~неделю, потом спросит снова). Убрать предупреждение: свой корневой сертификат, установленный на телефон, или HTTP (но без HTTPS браузер не даёт Wake Lock). Новый IP ПК → новый сертификат → предупреждение снова.
- Сервер слушает 0.0.0.0: Windows спросит доступ — разрешить в **частной** сети. Для проверок без окна брандмауэра запускать `Bridge(host="127.0.0.1")`.
- Работает только в одной сети; фоновых уведомлений на телефоне нет; при блокировке экрана передача рвётся (страница держит Wake Lock).
- Cookie `SameSite=Lax`, не Strict: вход по QR — переход из камеры, Strict-cookie потерялась бы на редиректе.
- QR несёт `?k=PIN`; сервер ставит cookie и редиректит на `/`. 5 неверных PIN → блок IP на минуту.
- Файл пишется в `.most-<id>.part`, потом `os.rename` в свободное имя («а (1).txt») — в Windows rename не перезаписывает.
- CSP `default-src 'self'`: никаких inline-скриптов и внешних CDN на странице телефона.
- События шины вызываются в потоке сервера (или окна, если `offer_*` звал GUI) → `EventRelay` (`Signal(str, object)`), AutoConnection сам решает. Меню трея (pystray) — чужой поток: только `.emit` сигналов окна.
- Закрытие окна прячет его (`setQuitOnLastWindowClosed(False)`); выход — `quit_requested` → `app.quit()`, затем `tray.stop()`, `service.stop()`.
- Пузыри отправленного добавляются по событиям `file_offered/text_offered` (в `file_offered` есть `path`), а не по ответу `offer_*`.
- QLabel с переносом в пузыре сжимается в узкую колонку: `TextBubble.fit()` ставит мин. ширину по тексту; шрифт из QSS известен только после `ensurePolished()`.
- До `show()` у виджетов `isVisible()` = False — для «пустой ленты» проверять `isHidden()`.
- Значки — символы Segoe MDL2 Assets, в коде как `\uXXXX`; скрипты правки могут превратить escape в сам символ — проверять.
- Проверка окна: `BridgeService(host="127.0.0.1", port=0, tls=False, data_dir=tmp, downloads=tmp)` + `win.grab().save()`; `MOST_THEME` для второй темы.
- Лента общая: всё с одного телефона видят остальные; с ПК — всем (`device_id=None`) или одному. Свой элемент отправителю по SSE не шлём (он добавляет его сам по ответу).
- Браузер телефона (например, Adblock Browser) скачивает файл молча и не говорит, куда: путь странице недоступен — показывать самим («сохранено в Загрузки телефона»).
- Файл «доставлен» — когда скачан целиком (отдаём сами кусками, без Range); текст — как только попал на страницу.
- Не возвращать из обработчика уже `prepare()`-нутый `FileResponse` — aiohttp падает (`assert writer is not None`).
- Открытый SSE держит сервер при остановке → `AppRunner(shutdown_timeout=2)`.
- Тестовый сервер в фоне: TaskStop может не убить python — проверять порт (`Get-NetTCPConnection -LocalPort N`).
- PyInstaller: `most/__main__.py` с относительными импортами нельзя брать точкой входа → `packaging/launcher.py`. `WEB_DIR = Path(__file__).parent / "web"` работает, т.к. web кладётся в `most/web` внутри exe.
- PyInstaller тянет лишнее: numpy (через PIL), `opengl32sw.dll`, Qt Quick/QML/PDF (через плагины Qt), переводы — выкинуто в `most.spec` (73 → 41 МБ). Новая зависимость от Qt-модуля → проверить, не попала ли под `DROP`.
- `build.ps1` с кириллицей — сохранять в UTF-8 **с BOM** (иначе PowerShell 5.1 читает как ANSI). Edit/Write могут снять BOM.
- Onefile = два процесса `Tropka.exe` (загрузчик + программа с окном); окно у дочернего. Убивать дочерний — загрузчик сам удалит `%TEMP%\_MEI…`.
- Exe без консоли: `sys.stdout` = None → `--console` в exe не работает, только `python -m most --console`.
- Exe не подписан: SmartScreen «Windows защитил…» → «Подробнее → Выполнить». Брандмауэр привязан к пути exe: перенос → спросит снова.
- Окно брандмауэра Windows может не появиться (или «Отмена» → блокирующее правило, оно сильнее разрешающего) — поэтому `firewall.py`. Проверка только в exe: из исходников правило пришлось бы давать python.exe.
- netsh пишет поля по-английски при кодовой странице 65001 и по-русски при 866 — `parse_rules` понимает оба; правила только UDP (Windows создаёт пару TCP+UDP) не считаются.
- Чтение правил брандмауэра через `Get-NetFirewallRule`/`ApplicationFilter` без админа — «Access denied»; netsh — работает.
- Onefile-exe стартует ~8–10 с (распаковка в `%TEMP%`) — в проверках ждать порт, а не фиксированную паузу.
- `Get-CimInstance Win32_Process` на этой машине сломан — дочерние процессы искать `Get-Process -Name Tropka`.
- Ход скачивания на телефоне: браузер странице ничего не сообщает → сервер, отдавая файл кусками, шлёт по SSE этому устройству `{"type":"dl", state: start|progress|done|error}`. Нет `start` за 15 с → «не началось» + «Повторить» (поздний `start` всё равно подхватится). После переподключения `loadFeed` ставит «готово» по `delivered`.
- Кнопку `<a download>` убирать из DOM только через `setTimeout(0)`: отсоединённая ссылка не скачивает.
- «Открыть папку» на Android убрано: intent'ы (`VIEW_DOWNLOADS`, VIEW `content://…documents/document/primary%3ADownload` через DocumentsUI, Files by Google) на настоящем телефоне папку не открыли. После скачивания — только надпись «Открыть: приложение «Файлы» → «Загрузки»» и «Посмотреть» (для типов из `VIEW_TYPES`). Не возвращать без проверки на телефоне.
- Свёрнутый браузер телефона рвёт/замораживает SSE, а EventSource переподключается не сразу → `visibilitychange` (видима) и `pageshow` (`persisted`) зовут `reconnect()`: новый EventSource + `loadFeed`. При «Нет связи» в шапке кнопка «Переподключить». ПК не пищит на каждое возвращение: звук «online» не чаще раза в 30 с после отключения.
- «Посмотреть» (`?view=1`) — запасной путь (iPhone, ПК, неудача intent), только типы из `VIEW_TYPES` (картинки, видео, аудио, txt), с `CSP: sandbox`: html/svg из общей ленты иначе выполнили бы скрипт на нашем адресе. Просмотр не считается доставкой. Middleware ставит CSP через `setdefault`.
- Звук в браузере — только после касания: AudioContext создаётся в `pointerdown/touchend/keydown`; программный `.click()` его не разблокирует.
- «Очистить» (корзина в шапке окна, кнопка у «Ленты» на телефоне) стирает общую ленту у всех: `history`+`deliveries`, файлы остаются. Сервер шлёт всем SSE `{"type":"clear"}` и событие `feed_cleared` (окно: `FeedView.clear()` пересоздаёт виджет ленты). Телефон не трогает свои ещё идущие отправки.
- После очистки id истории не начинаются с 1: SQLite без AUTOINCREMENT взял бы max+1 → `meta.history_floor`, id в `add_history` задаётся явно. Иначе старое «скачано» и открытые страницы спутали бы новые элементы со старыми.
- QR-окно закрывается само, когда подключился телефон (`device_joined` или `device_online`), кроме тех, что были на связи при открытии QR (`_qr_skip`): их переподключение — не повод.
- «Помощь проекту» → https://dalink.to/olegche (`config.DONATE_URL`): сердце в шапке окна, пункт меню трея, кнопка внизу страницы телефона (`index.html`, `target=_blank`).
- Имена файлов — только латиницей: exe `Tropka.exe` (`most.spec`, `OriginalFilename` в `make_assets.py`), принятые файлы в «Загрузки\Tropka». По-русски — только тексты интерфейса и имя правила брандмауэра «Тропка».
