# Разработка MeDVeD

Этот файл — для тех, кто собирает приложение из исходников или выпускает релизы
(то есть для мейнтейнера). Обычным пользователям он не нужен — им достаточно
готового `MeDVeD.exe` со [страницы релизов](https://github.com/Jellytyt/MeDVeD/releases/latest).
Инструкция для пользователей — в [README.md](README.md).

## Структура проекта

| Файл | Зачем |
|---|---|
| `app.py` | Главный модуль: весь UI (CustomTkinter), логика подключения, трей, авто-обновление, статистика |
| `config.py` | Сборка JSON-конфига sing-box из профилей (outbounds, routing, TUN, urltest/selector) |
| `parser.py` | Парсинг ссылок (vless/vmess/trojan/ss/hysteria2/tuic) и экспорт обратно в ссылку |
| `models.py` | Датаклассы `VlessProfile` и `AppSettings` + сериализация |
| `storage.py` | Чтение/запись `profiles.json` и `settings.json` в `%LOCALAPPDATA%\vless_manager\` |
| `MeDVeD.spec` | Конфиг PyInstaller (onedir: папка `MeDVeD\` = `MeDVeD.exe` + `_internal\`, встраивание sing-box.exe и иконок) |
| `MeDVeD.iss` | Скрипт Inno Setup: заворачивает `dist\MeDVeD\` в установщик `MeDVeD-Setup-*.exe` (per-user, без UAC) |
| `.github/workflows/build.yml` | CI: по тегу собирает onedir, пакует установщиком и публикует Release |
| `CHANGELOG.md` | Заметки по версиям; CI берёт отсюда описание релиза |

При разработке (не frozen) личные данные лежат там же — в
`%LOCALAPPDATA%\vless_manager\`, так что dev-запуск делит профили и настройки с
установленной версией. Будь осторожен, тестируя удаление профилей.

## Сборка

```powershell
git clone https://github.com/Jellytyt/MeDVeD.git
cd MeDVeD

# Положить sing-box.exe в корень репо (скачать из https://github.com/SagerNet/sing-box/releases)

python -m pip install -r requirements.txt
python -m pip install pyinstaller

python -m PyInstaller --noconfirm MeDVeD.spec
# Готовая папка приложения: dist\MeDVeD\ (MeDVeD.exe + _internal\)
```

Чтобы собрать установщик локально, нужен [Inno Setup 6](https://jrsoftware.org/isdl.php),
затем:

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DMyAppVersion=0.9.7 MeDVeD.iss
# Готовый установщик: installer_output\MeDVeD-Setup-0.9.7.exe
```

Для запуска из исходников без сборки достаточно `python app.py` (TUN-режим всё
равно требует прав администратора).

## Релиз

1. Поднять `__version__` в [app.py](app.py)
2. Добавить раздел `## vX.Y.Z` в [CHANGELOG.md](CHANGELOG.md) (CI вытянет его в
   описание Release — заголовок должен точно совпадать с тегом)
3. `git tag vX.Y.Z && git push origin vX.Y.Z`

Дальше [GitHub Actions](.github/workflows/build.yml) сам:

- Скачает свежий sing-box.exe от SagerNet
- Соберёт папку `dist\MeDVeD\` через PyInstaller (onedir)
- Упакует её в установщик `MeDVeD-Setup-X.Y.Z.exe` через Inno Setup
- Создаст Release с прикреплённым установщиком
- Подтянет описание из CHANGELOG.md

Версию в `app.py` и заголовок в `CHANGELOG.md` легко забыть синхронизировать с
тегом — если CI не находит секцию по тегу, описание релиза будет пустым.
