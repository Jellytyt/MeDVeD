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
| `MeDVeD.spec` | Конфиг PyInstaller (встраивание sing-box.exe, иконки, иконка приложения) |
| `.github/workflows/build.yml` | CI: по тегу собирает exe и публикует Release |
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
# Готовый exe лежит в dist\MeDVeD.exe
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
- Соберёт MeDVeD.exe через PyInstaller
- Создаст Release с прикреплённым exe
- Подтянет описание из CHANGELOG.md

Версию в `app.py` и заголовок в `CHANGELOG.md` легко забыть синхронизировать с
тегом — если CI не находит секцию по тегу, описание релиза будет пустым.
