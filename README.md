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

## Запуск

```bash
python run.py
```

Приложение слушает `127.0.0.1:10061`. SSL-сертификат не используется.

Проверка состояния:

```bash
curl http://127.0.0.1:10061/health
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

Zabbix должен отправлять `POST` запрос на:

```text
http://127.0.0.1:10061/zabbix
```

Заголовок:

```text
Content-Type: application/json
```

Поля JSON должны соответствовать структуре выше: `message_type`, `problem_ident`, `subject_text`, `body_text`.
