# Zabbix Matrix Bot

Бот принимает HTTP JSON-уведомления от Zabbix и отправляет их в комнату Matrix.

- `problem` отправляется обычным сообщением в комнату.
- `solution` отправляется в Matrix thread под ранее отправленной проблемой.
- Связка `problem_ident -> Matrix event_id` хранится в SQLite `./database/database.sqlite3`.
- После успешной отправки `solution` запись о проблеме удаляется.

## Требования

- Python 3.10+.
- Доступ к Matrix homeserver.
- Access token пользователя/бота Matrix, который имеет право писать в нужную комнату.
- Для запуска как демон: Linux с `systemd` и права `sudo` для установки сервиса.
- Для автоматической настройки Zabbix через `install-on-zabbix.py`: Zabbix 7.0+ и API token или учётная запись с правами администратора.

## Установка

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Заполните `.env`:

```env
MATRIX_HOMESERVER=https://matrix.example.org
MATRIX_ROOM_ID=!roomid:example.org
MATRIX_ACCESS_TOKEN=your_access_token_here

APP_HOST=127.0.0.1
APP_PORT=10061
DATABASE_PATH=./database/database.sqlite3
LOG_DIR=./logs
```

Параметры:

| Переменная | Описание |
| --- | --- |
| `MATRIX_HOMESERVER` | URL Matrix homeserver, например `https://matrix.example.org` |
| `MATRIX_ROOM_ID` | ID комнаты Matrix, куда бот будет отправлять уведомления |
| `MATRIX_ACCESS_TOKEN` | Access token пользователя/бота Matrix |
| `APP_HOST` | IP-адрес, на котором слушает HTTP-сервер; по умолчанию `127.0.0.1` |
| `APP_PORT` | Порт HTTP-сервера; по умолчанию `10061` |
| `DATABASE_PATH` | Путь к SQLite базе; по умолчанию `./database/database.sqlite3` |
| `LOG_DIR` | Каталог для файлов логов; по умолчанию `./logs` |

## Запуск

```bash
python run.py
```

Приложение слушает `127.0.0.1:10061`. SSL-сертификат не используется.

Проверка состояния:

```bash
curl http://127.0.0.1:10061/health
```

## Запуск как демон с автозапуском

Самый простой вариант для Linux-сервера — запустить бота как `systemd`-сервис. В этом режиме приложение работает в фоне, автоматически стартует после перезагрузки и перезапускается при сбое.

Сначала выполните обычную установку, создайте `.env` и проверьте ручной запуск:

```bash
python run.py
```

Установщик ожидает, что зависимости установлены в `.venv` внутри каталога проекта, а файл `.env` уже создан. Каталог проекта не должен содержать пробелов в пути.

Затем установите и запустите сервис:

```bash
sudo bash install-daemon.sh
```

Скрипт создаёт `/etc/systemd/system/zabtomat-bot.service` для текущего каталога проекта и пользователя, от имени которого был запущен `sudo`.

Управление сервисом:

```bash
sudo systemctl status zabtomat-bot
sudo systemctl restart zabtomat-bot
sudo systemctl stop zabtomat-bot
```

Просмотр логов `systemd`:

```bash
sudo journalctl -u zabtomat-bot -f
```

Отключить автозапуск и остановить сервис:

```bash
sudo systemctl disable --now zabtomat-bot
```

Если вы изменили код или `.env`, перезапустите сервис:

```bash
sudo systemctl restart zabtomat-bot
```

## Endpoint для Zabbix

`POST /zabbix`

Тело запроса:

```json
{
  "message_type": "problem",
  "problem_ident": "12345",
  "subject_text": "High CPU load on web-01",
  "body_text": "CPU load is above threshold for 5 minutes"
}
```

Для решения проблемы:

```json
{
  "message_type": "solution",
  "problem_ident": "12345",
  "subject_text": "Resolved: High CPU load on web-01",
  "body_text": "CPU load returned to normal"
}
```

Формат Matrix-сообщения:

````markdown
#### SUBJECT
```
BODY
```
````

## База данных

База создаётся автоматически при старте приложения. Модель таблицы и асинхронные операции с SQLite реализованы через `peewee-async`.

Таблица `problems`:

| Поле | Тип | Описание |
| --- | --- | --- |
| `problem_ident` | text primary key | ID проблемы из Zabbix |
| `message_ident` | text | Matrix event ID сообщения о проблеме |

## Логи

Логи пишутся в `./logs` в файлы вида:

```text
bot_10-07-26_10-00-00.log
```

Каждый день в `00:00` текущий лог ротируется. Ротированный файл добавляется в архив `./logs.zip`; архив дополняется, а не перезаписывается.

Вывод в STDERR отключён.

## Пример настройки Zabbix webhook

### Автоматическая настройка Zabbix

В проекте есть скрипт `install-on-zabbix.py`, который автоматически создаёт в Zabbix всё необходимое для отправки уведомлений в бота:

- media type `matrix-problem` для проблем;
- media type `matrix-solution` для восстановлений;
- пользователя `matrix-notification`;
- группу `Matrix notification users`;
- action `Matrix notifications`.

Пример запуска с API token:

```bash
python install-on-zabbix.py \
  --zabbix-url https://zabbix.example.org/zabbix \
  --api-token YOUR_ZABBIX_API_TOKEN \
  --bot-url http://127.0.0.1:10061/zabbix
```

Если `--api-token` не указан, скрипт спросит логин и пароль пользователя Zabbix API интерактивно:

```bash
python install-on-zabbix.py --zabbix-url https://zabbix.example.org/zabbix
```

Полезные параметры:

| Параметр | Описание |
| --- | --- |
| `--bot-url` | URL endpoint бота, который будет записан в Zabbix; по умолчанию `http://127.0.0.1:10061/zabbix` |
| `--notification-user` | Имя создаваемого пользователя Zabbix; по умолчанию `matrix-notification` |
| `--notification-user-password` | Пароль создаваемого пользователя; если не задан, будет сгенерирован |
| `--user-group` | Имя группы создаваемого пользователя |
| `--action-name` | Имя создаваемого action |
| `--no-update-existing` | Не обновлять уже существующие объекты Zabbix |
| `--insecure` | Не проверять TLS-сертификат Zabbix API |

Также можно передать значения через переменные окружения:

```bash
ZABBIX_API_TOKEN=YOUR_ZABBIX_API_TOKEN \
MATRIX_BOT_ZABBIX_URL=http://127.0.0.1:10061/zabbix \
python install-on-zabbix.py --zabbix-url https://zabbix.example.org/zabbix
```

### Ручная настройка webhook

Zabbix должен отправлять `POST` запрос на:

```text
http://127.0.0.1:10061/zabbix
```

Заголовок:

```text
Content-Type: application/json
```

Поля JSON должны соответствовать структуре выше: `message_type`, `problem_ident`, `subject_text`, `body_text`.
