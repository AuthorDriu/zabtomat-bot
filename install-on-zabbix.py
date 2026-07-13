#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import secrets
import ssl
import string
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_ZABBIX_USER = "matrix-notification"
DEFAULT_USER_GROUP = "Matrix notification users"
DEFAULT_ACTION_NAME = "Matrix notifications"
DEFAULT_BOT_URL = "http://127.0.0.1:10061/zabbix"
PROBLEM_MEDIA_TYPE_NAME = "matrix-problem"
SOLUTION_MEDIA_TYPE_NAME = "matrix-solution"
UPDATE_MEDIA_TYPE_NAME = "matrix-update"
MEDIA_SENDTO = "zabbix-matrix-bot"

WEBHOOK_SCRIPT = r"""
try {
    var params = JSON.parse(value);

    if (!params.url) {
        throw 'Parameter "url" is required.';
    }
    if (!params.message_type) {
        throw 'Parameter "message_type" is required.';
    }
    if (!params.problem_ident) {
        throw 'Parameter "problem_ident" is required.';
    }

    var payload = {
        message_type: params.message_type,
        problem_ident: params.problem_ident,
        subject_text: params.subject_text || '',
        body_text: params.body_text || ''
    };

    var request = new HttpRequest();
    request.addHeader('Content-Type: application/json');

    var response = request.post(params.url, JSON.stringify(payload));
    var status = request.getStatus();

    if (status < 200 || status >= 300) {
        throw 'HTTP ' + status + ' from Matrix notification endpoint: ' + response;
    }

    return 'OK';
}
catch (error) {
    throw 'Matrix notification webhook failed: ' + error;
}
""".strip()

PROBLEM_SUBJECT = "ПРОБЛЕМА [{EVENT.SEVERITY}]: {EVENT.NAME}"
PROBLEM_MESSAGE = """Событие: ПРОБЛЕМА
Важность: {EVENT.SEVERITY}
Статус события: {EVENT.STATUS}

Проблема: {EVENT.NAME}
Триггер: {TRIGGER.NAME}
Описание триггера: {TRIGGER.DESCRIPTION}
Оперативные данные: {EVENT.OPDATA}

Узел: {HOST.NAME}
IP/DNS: {HOST.IP} / {HOST.DNS}

Время начала: {EVENT.DATE} {EVENT.TIME}
ID проблемы: {EVENT.ID}
ID триггера: {TRIGGER.ID}
URL триггера: {TRIGGER.URL}

Значения элементов данных:
1. {ITEM.NAME1} ({HOST.NAME1}:{ITEM.KEY1}) = {ITEM.VALUE1}
2. {ITEM.NAME2} ({HOST.NAME2}:{ITEM.KEY2}) = {ITEM.VALUE2}
3. {ITEM.NAME3} ({HOST.NAME3}:{ITEM.KEY3}) = {ITEM.VALUE3}

Теги события:
{EVENT.TAGS}
""".strip()

SOLUTION_SUBJECT = "ВОССТАНОВЛЕНО [{EVENT.SEVERITY}]: {EVENT.NAME}"
SOLUTION_MESSAGE = """Событие: ВОССТАНОВЛЕНИЕ
Важность: {EVENT.SEVERITY}
Текущий статус: {EVENT.STATUS}

Проблема: {EVENT.NAME}
Триггер: {TRIGGER.NAME}
Описание триггера: {TRIGGER.DESCRIPTION}
Оперативные данные: {EVENT.OPDATA}

Узел: {HOST.NAME}
IP/DNS: {HOST.IP} / {HOST.DNS}

Начало проблемы: {EVENT.DATE} {EVENT.TIME}
Восстановлено: {EVENT.RECOVERY.DATE} {EVENT.RECOVERY.TIME}
Длительность: {EVENT.DURATION}

ID проблемы: {EVENT.ID}
ID события восстановления: {EVENT.RECOVERY.ID}
ID триггера: {TRIGGER.ID}
URL триггера: {TRIGGER.URL}

Последние значения элементов данных:
1. {ITEM.NAME1} ({HOST.NAME1}:{ITEM.KEY1}) = {ITEM.VALUE1}
2. {ITEM.NAME2} ({HOST.NAME2}:{ITEM.KEY2}) = {ITEM.VALUE2}
3. {ITEM.NAME3} ({HOST.NAME3}:{ITEM.KEY3}) = {ITEM.VALUE3}

Теги события:
{EVENT.TAGS}
""".strip()

UPDATE_SUBJECT = "ОБНОВЛЕНИЕ [{EVENT.SEVERITY}]: {EVENT.NAME}"
UPDATE_MESSAGE = """Событие: ОБНОВЛЕНИЕ ПРОБЛЕМЫ
Важность: {EVENT.SEVERITY}
Текущий статус: {EVENT.STATUS}

Проблема: {EVENT.NAME}
Триггер: {TRIGGER.NAME}
Описание триггера: {TRIGGER.DESCRIPTION}
Оперативные данные: {EVENT.OPDATA}

Узел: {HOST.NAME}
IP/DNS: {HOST.IP} / {HOST.DNS}

Начало проблемы: {EVENT.DATE} {EVENT.TIME}
Обновлено: {EVENT.UPDATE.DATE} {EVENT.UPDATE.TIME}
Длительность: {EVENT.DURATION}

ID проблемы: {EVENT.ID}
ID триггера: {TRIGGER.ID}
URL триггера: {TRIGGER.URL}

Пользователь: {USER.FULLNAME} ({USER.USERNAME})
Действие: {EVENT.UPDATE.ACTION}
Сообщение обновления:
{EVENT.UPDATE.MESSAGE}

Последние значения элементов данных:
1. {ITEM.NAME1} ({HOST.NAME1}:{ITEM.KEY1}) = {ITEM.VALUE1}
2. {ITEM.NAME2} ({HOST.NAME2}:{ITEM.KEY2}) = {ITEM.VALUE2}
3. {ITEM.NAME3} ({HOST.NAME3}:{ITEM.KEY3}) = {ITEM.VALUE3}

Теги события:
{EVENT.TAGS}
""".strip()


class ZabbixAPIError(RuntimeError):
    pass


@dataclass
class Args:
    zabbix_url: str
    bot_url: str
    api_token: str | None
    zabbix_user: str | None
    zabbix_password: str | None
    notification_user: str
    notification_user_password: str | None
    user_group: str
    action_name: str
    role_id: str | None
    no_update_existing: bool
    insecure: bool
    timeout: int


class ZabbixAPI:
    def __init__(self, url: str, timeout: int, insecure: bool) -> None:
        self.url = normalize_api_url(url)
        self.timeout = timeout
        self.auth_token: str | None = None
        self._request_id = 0
        self._ssl_context = ssl._create_unverified_context() if insecure else None

    def call(self, method: str, params: Any | None = None, authenticated: bool = True) -> Any:
        self._request_id += 1
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
            "params": {} if params is None else params,
            "id": self._request_id,
        }

        headers = {"Content-Type": "application/json-rpc"}
        if authenticated:
            if not self.auth_token:
                raise ZabbixAPIError(f"API method {method!r} requires authentication")
            headers["Authorization"] = f"Bearer {self.auth_token}"

        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(self.url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout,
                context=self._ssl_context,
            ) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            raise ZabbixAPIError(f"HTTP {error.code} for {method}: {body}") from error
        except urllib.error.URLError as error:
            raise ZabbixAPIError(f"Cannot connect to Zabbix API at {self.url}: {error}") from error

        try:
            result = json.loads(response_body)
        except json.JSONDecodeError as error:
            raise ZabbixAPIError(f"Invalid JSON response for {method}: {response_body}") from error

        if "error" in result:
            api_error = result["error"]
            message = api_error.get("message", "API error")
            details = api_error.get("data")
            if details:
                message = f"{message}: {details}"
            raise ZabbixAPIError(f"{method} failed: {message}")

        return result.get("result")

    def login(self, user: str, password: str) -> None:
        logging.info("Выполняю вход в Zabbix API пользователем %s", user)
        try:
            self.auth_token = self.call(
                "user.login",
                {"username": user, "password": password},
                authenticated=False,
            )
        except ZabbixAPIError as error:
            if "Invalid parameter" not in str(error) or "username" not in str(error):
                raise
            logging.info("Повторяю вход со старым именем поля user вместо username")
            self.auth_token = self.call(
                "user.login",
                {"user": user, "password": password},
                authenticated=False,
            )

    def logout(self) -> None:
        if not self.auth_token:
            return
        try:
            self.call("user.logout", [], authenticated=True)
        except ZabbixAPIError as error:
            logging.warning("Не удалось закрыть API-сессию: %s", error)
        finally:
            self.auth_token = None


def normalize_api_url(url: str) -> str:
    url = url.strip()
    if not url:
        raise ValueError("Zabbix URL is empty")
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme:
        url = "https://" + url
        parsed = urllib.parse.urlparse(url)
    if parsed.path.endswith("api_jsonrpc.php"):
        return url
    return url.rstrip("/") + "/api_jsonrpc.php"


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )


def parse_args() -> Args:
    parser = argparse.ArgumentParser(
        description="Автоматически настраивает Zabbix 7.0+ для отправки уведомлений в Zabbix Matrix Bot.",
    )
    parser.add_argument("--zabbix-url", help="URL Zabbix или api_jsonrpc.php, например https://zabbix.example.org/zabbix")
    parser.add_argument("--bot-url", default=os.getenv("MATRIX_BOT_ZABBIX_URL", DEFAULT_BOT_URL), help=f"URL endpoint бота, по умолчанию {DEFAULT_BOT_URL}")
    parser.add_argument("--api-token", default=os.getenv("ZABBIX_API_TOKEN"), help="Zabbix API token; можно также задать ZABBIX_API_TOKEN")
    parser.add_argument("--zabbix-user", default=os.getenv("ZABBIX_USER"), help="Пользователь Zabbix API, если не используется token")
    parser.add_argument("--zabbix-password", default=os.getenv("ZABBIX_PASSWORD"), help="Пароль Zabbix API, если не используется token")
    parser.add_argument("--notification-user", default=DEFAULT_ZABBIX_USER, help=f"Создаваемый пользователь Zabbix, по умолчанию {DEFAULT_ZABBIX_USER}")
    parser.add_argument("--notification-user-password", help="Пароль для создаваемого пользователя; если не задан, будет сгенерирован")
    parser.add_argument("--user-group", default=DEFAULT_USER_GROUP, help=f"Группа создаваемого пользователя, по умолчанию {DEFAULT_USER_GROUP!r}")
    parser.add_argument("--action-name", default=DEFAULT_ACTION_NAME, help=f"Имя action в Zabbix, по умолчанию {DEFAULT_ACTION_NAME!r}")
    parser.add_argument("--role-id", help="Role ID для создаваемого пользователя; если не задан, скрипт найдёт роль обычного User")
    parser.add_argument("--no-update-existing", action="store_true", help="Не обновлять уже существующие media types, группу, пользователя и action")
    parser.add_argument("--insecure", action="store_true", help="Не проверять TLS-сертификат Zabbix API")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout в секундах")

    namespace = parser.parse_args()

    zabbix_url = namespace.zabbix_url or prompt("Zabbix URL", required=True)

    api_token = namespace.api_token
    zabbix_user = namespace.zabbix_user
    zabbix_password = namespace.zabbix_password
    if not api_token:
        zabbix_user = zabbix_user or prompt("Zabbix API user", default="Admin", required=True)
        zabbix_password = zabbix_password or getpass.getpass("Zabbix API password: ")

    return Args(
        zabbix_url=zabbix_url,
        bot_url=namespace.bot_url,
        api_token=api_token,
        zabbix_user=zabbix_user,
        zabbix_password=zabbix_password,
        notification_user=namespace.notification_user,
        notification_user_password=namespace.notification_user_password,
        user_group=namespace.user_group,
        action_name=namespace.action_name,
        role_id=namespace.role_id,
        no_update_existing=namespace.no_update_existing,
        insecure=namespace.insecure,
        timeout=namespace.timeout,
    )


def prompt(label: str, default: str | None = None, required: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"{label}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return default
        if not required:
            return ""
        print("Значение обязательно.", file=sys.stderr)


def ensure_minimum_version(api: ZabbixAPI) -> None:
    version = api.call("apiinfo.version", authenticated=False)
    logging.info("Zabbix API version: %s", version)
    major_minor = tuple(int(part) for part in str(version).split(".")[:2])
    if major_minor < (7, 0):
        raise ZabbixAPIError(f"Нужен Zabbix 7.0+, обнаружен {version}")


def find_one(api: ZabbixAPI, method: str, params: dict[str, Any], id_field: str, label: str) -> dict[str, Any] | None:
    result = api.call(method, params)
    if not result:
        return None
    if len(result) > 1:
        ids = ", ".join(str(item.get(id_field, "?")) for item in result)
        logging.warning("Найдено несколько объектов %s (%s), использую первый", label, ids)
    return result[0]


def media_type_params(bot_url: str, message_type: str) -> list[dict[str, str]]:
    return [
        {"name": "url", "value": bot_url},
        {"name": "message_type", "value": message_type},
        {"name": "problem_ident", "value": "{EVENT.ID}"},
        {"name": "subject_text", "value": "{ALERT.SUBJECT}"},
        {"name": "body_text", "value": "{ALERT.MESSAGE}"},
    ]


def media_type_message_templates(message_type: str) -> list[dict[str, str]]:
    if message_type == "problem":
        return [
            {
                "eventsource": "0",
                "recovery": "0",
                "subject": PROBLEM_SUBJECT,
                "message": PROBLEM_MESSAGE,
            }
        ]

    if message_type == "solution":
        return [
            {
                "eventsource": "0",
                "recovery": "1",
                "subject": SOLUTION_SUBJECT,
                "message": SOLUTION_MESSAGE,
            }
        ]

    if message_type == "update":
        return [
            {
                "eventsource": "0",
                "recovery": "2",
                "subject": UPDATE_SUBJECT,
                "message": UPDATE_MESSAGE,
            }
        ]

    raise ValueError(f"Unknown message type: {message_type}")


def desired_media_type(name: str, bot_url: str, message_type: str) -> dict[str, Any]:
    return {
        "name": name,
        "type": 4,
        "status": 0,
        "script": WEBHOOK_SCRIPT,
        "timeout": "10s",
        "maxattempts": "3",
        "attempt_interval": "10s",
        "parameters": media_type_params(bot_url, message_type),
        "message_templates": media_type_message_templates(message_type),
        "description": "Managed by install-on-zabbix.py for Zabbix Matrix Bot.",
    }


def ensure_media_type(api: ZabbixAPI, name: str, bot_url: str, message_type: str, no_update: bool) -> str:
    existing = find_one(
        api,
        "mediatype.get",
        {
            "output": ["mediatypeid", "name", "type", "status"],
            "selectParameters": "extend",
            "filter": {"name": [name]},
        },
        "mediatypeid",
        f"media type {name!r}",
    )
    desired = desired_media_type(name, bot_url, message_type)

    if existing:
        mediatypeid = existing["mediatypeid"]
        logging.info("Media type %s уже существует: id=%s", name, mediatypeid)
        if no_update:
            return mediatypeid
        update_payload = {"mediatypeid": mediatypeid, **desired}
        api.call("mediatype.update", update_payload)
        logging.info("Media type %s обновлён", name)
        return mediatypeid

    result = api.call("mediatype.create", desired)
    mediatypeid = result["mediatypeids"][0]
    logging.info("Создан media type %s: id=%s", name, mediatypeid)
    return mediatypeid


def find_user_role(api: ZabbixAPI, explicit_role_id: str | None) -> str:
    if explicit_role_id:
        logging.info("Использую заданный roleid=%s", explicit_role_id)
        return explicit_role_id

    roles = api.call("role.get", {"output": ["roleid", "name", "type"], "sortfield": "roleid"})
    user_roles = [role for role in roles if str(role.get("type")) == "1"]
    if not user_roles:
        raise ZabbixAPIError("Не удалось найти роль обычного пользователя Zabbix; задайте --role-id")

    preferred = next((role for role in user_roles if role.get("name") == "User role"), user_roles[0])
    logging.info("Использую роль пользователя %s: roleid=%s", preferred.get("name"), preferred["roleid"])
    return preferred["roleid"]


def get_all_host_group_rights(api: ZabbixAPI) -> list[dict[str, Any]]:
    groups = api.call("hostgroup.get", {"output": ["groupid", "name"]})
    rights = [{"id": group["groupid"], "permission": 2} for group in groups]
    logging.info("Группа уведомлений получит read-доступ к host groups: %d", len(rights))
    return rights


def ensure_user_group(api: ZabbixAPI, name: str, rights: list[dict[str, Any]], no_update: bool) -> str:
    existing = find_one(
        api,
        "usergroup.get",
        {"output": ["usrgrpid", "name"], "filter": {"name": [name]}},
        "usrgrpid",
        f"user group {name!r}",
    )
    payload: dict[str, Any] = {"name": name, "users_status": 0}
    if rights:
        payload["hostgroup_rights"] = rights

    if existing:
        usrgrpid = existing["usrgrpid"]
        logging.info("User group %s уже существует: id=%s", name, usrgrpid)
        if not no_update:
            api.call("usergroup.update", {"usrgrpid": usrgrpid, **payload})
            logging.info("User group %s обновлена", name)
        return usrgrpid

    result = api.call("usergroup.create", payload)
    usrgrpid = result.get("usrgrpids", result.get("groupids"))[0]
    logging.info("Создана user group %s: id=%s", name, usrgrpid)
    return usrgrpid


def generated_password() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(32))
        if (
            any(ch.islower() for ch in password)
            and any(ch.isupper() for ch in password)
            and any(ch.isdigit() for ch in password)
            and any(ch in "!@#$%^&*()-_=+" for ch in password)
        ):
            return password


def desired_user_media(mediatypeid: str) -> dict[str, Any]:
    return {
        "mediatypeid": mediatypeid,
        "sendto": [MEDIA_SENDTO],
        "active": 0,
        "severity": 63,
        "period": "1-7,00:00-24:00",
    }


def compact_media(media: dict[str, Any]) -> dict[str, Any]:
    result = {
        "mediatypeid": media["mediatypeid"],
        "sendto": media.get("sendto") or [MEDIA_SENDTO],
        "active": int(media.get("active", 0)),
        "severity": int(media.get("severity", 63)),
        "period": media.get("period") or "1-7,00:00-24:00",
    }
    if media.get("mediaid"):
        result["mediaid"] = media["mediaid"]
    if isinstance(result["sendto"], str):
        result["sendto"] = [result["sendto"]]
    return result


def merge_user_medias(existing: list[dict[str, Any]], desired: list[dict[str, Any]]) -> list[dict[str, Any]]:
    desired_by_type = {str(media["mediatypeid"]): media for media in desired}
    merged: list[dict[str, Any]] = []
    seen_types: set[str] = set()

    for media in existing:
        mediatypeid = str(media.get("mediatypeid"))
        if mediatypeid in desired_by_type:
            replacement = {**desired_by_type[mediatypeid]}
            if media.get("mediaid"):
                replacement["mediaid"] = media["mediaid"]
            merged.append(replacement)
            seen_types.add(mediatypeid)
        else:
            merged.append(compact_media(media))

    for mediatypeid, media in desired_by_type.items():
        if mediatypeid not in seen_types:
            merged.append(media)

    return merged


def ensure_user(
    api: ZabbixAPI,
    username: str,
    role_id: str,
    usrgrpid: str,
    problem_mediatypeid: str,
    solution_mediatypeid: str,
    update_mediatypeid: str,
    password: str | None,
    no_update: bool,
) -> str:
    desired_medias = [
        desired_user_media(problem_mediatypeid),
        desired_user_media(solution_mediatypeid),
        desired_user_media(update_mediatypeid),
    ]
    existing = find_one(
        api,
        "user.get",
        {
            "output": ["userid", "username", "roleid"],
            "selectUsrgrps": ["usrgrpid", "name"],
            "selectMedias": "extend",
            "filter": {"username": [username]},
        },
        "userid",
        f"user {username!r}",
    )

    if existing:
        userid = existing["userid"]
        logging.info("Пользователь %s уже существует: id=%s", username, userid)
        if no_update:
            return userid

        usrgrps = compact_user_groups(existing.get("usrgrps", []), usrgrpid)
        medias = merge_user_medias(existing.get("medias", []), desired_medias)
        update_payload: dict[str, Any] = {"userid": userid, "usrgrps": usrgrps, "medias": medias}
        if password:
            update_payload["passwd"] = password
        api.call("user.update", update_payload)
        logging.info("Пользователь %s обновлён: группа и media types настроены", username)
        return userid

    user_password = password or generated_password()
    payload = {
        "username": username,
        "passwd": user_password,
        "roleid": role_id,
        "usrgrps": [{"usrgrpid": usrgrpid}],
        "medias": desired_medias,
    }
    result = api.call("user.create", payload)
    userid = result["userids"][0]
    logging.info("Создан пользователь %s: id=%s", username, userid)
    if not password:
        logging.info("Для пользователя %s сгенерирован случайный пароль; он не выводится и не сохраняется", username)
    return userid


def compact_user_groups(existing: list[dict[str, Any]], required_usrgrpid: str) -> list[dict[str, str]]:
    result = [{"usrgrpid": group["usrgrpid"]} for group in existing if group.get("usrgrpid")]
    if required_usrgrpid not in {group["usrgrpid"] for group in result}:
        result.append({"usrgrpid": required_usrgrpid})
    return result


def desired_action(
    action_name: str,
    userid: str,
    problem_mediatypeid: str,
    solution_mediatypeid: str,
    update_mediatypeid: str,
) -> dict[str, Any]:
    return {
        "name": action_name,
        "eventsource": 0,
        "status": 0,
        "esc_period": "1h",
        "pause_suppressed": 1,
        "filter": {
            "evaltype": 0,
            "conditions": [],
        },
        "operations": [
            {
                "operationtype": 0,
                "esc_step_from": 1,
                "esc_step_to": 1,
                "opmessage_usr": [{"userid": userid}],
                "opmessage": {
                    "default_msg": 1,
                    "mediatypeid": problem_mediatypeid,
                },
            }
        ],
        "recovery_operations": [
            {
                "operationtype": 0,
                "opmessage_usr": [{"userid": userid}],
                "opmessage": {
                    "default_msg": 1,
                    "mediatypeid": solution_mediatypeid,
                },
            }
        ],
        "update_operations": [
            {
                "operationtype": 0,
                "opmessage_usr": [{"userid": userid}],
                "opmessage": {
                    "default_msg": 1,
                    "mediatypeid": update_mediatypeid,
                },
            }
        ],
    }


def ensure_action(
    api: ZabbixAPI,
    action_name: str,
    userid: str,
    problem_mediatypeid: str,
    solution_mediatypeid: str,
    update_mediatypeid: str,
    no_update: bool,
) -> str:
    existing = find_one(
        api,
        "action.get",
        {
            "output": ["actionid", "name", "eventsource", "status"],
            "filter": {"name": [action_name], "eventsource": 0},
        },
        "actionid",
        f"action {action_name!r}",
    )
    desired = desired_action(action_name, userid, problem_mediatypeid, solution_mediatypeid, update_mediatypeid)

    if existing:
        actionid = existing["actionid"]
        logging.info("Action %s уже существует: id=%s", action_name, actionid)
        if not no_update:
            api.call("action.update", {"actionid": actionid, **desired})
            logging.info("Action %s обновлён", action_name)
        return actionid

    result = api.call("action.create", desired)
    actionid = result["actionids"][0]
    logging.info("Создан action %s: id=%s", action_name, actionid)
    return actionid


def install(args: Args) -> None:
    api = ZabbixAPI(args.zabbix_url, timeout=args.timeout, insecure=args.insecure)
    logging.info("Zabbix API endpoint: %s", api.url)
    logging.info("Matrix bot endpoint: %s", args.bot_url)

    ensure_minimum_version(api)

    if args.api_token:
        logging.info("Использую Zabbix API token из параметров/окружения")
        api.auth_token = args.api_token
        logged_in = False
    else:
        if not args.zabbix_user or not args.zabbix_password:
            raise ZabbixAPIError("Нужны --api-token или --zabbix-user/--zabbix-password")
        api.login(args.zabbix_user, args.zabbix_password)
        logged_in = True

    try:
        problem_mediatypeid = ensure_media_type(
            api,
            PROBLEM_MEDIA_TYPE_NAME,
            args.bot_url,
            "problem",
            args.no_update_existing,
        )
        solution_mediatypeid = ensure_media_type(
            api,
            SOLUTION_MEDIA_TYPE_NAME,
            args.bot_url,
            "solution",
            args.no_update_existing,
        )
        update_mediatypeid = ensure_media_type(
            api,
            UPDATE_MEDIA_TYPE_NAME,
            args.bot_url,
            "update",
            args.no_update_existing,
        )

        role_id = find_user_role(api, args.role_id)
        rights = get_all_host_group_rights(api)
        usrgrpid = ensure_user_group(api, args.user_group, rights, args.no_update_existing)
        userid = ensure_user(
            api,
            args.notification_user,
            role_id,
            usrgrpid,
            problem_mediatypeid,
            solution_mediatypeid,
            update_mediatypeid,
            args.notification_user_password,
            args.no_update_existing,
        )
        ensure_action(
            api,
            args.action_name,
            userid,
            problem_mediatypeid,
            solution_mediatypeid,
            update_mediatypeid,
            args.no_update_existing,
        )
    finally:
        if logged_in:
            api.logout()

    logging.info(
        "Готово: Zabbix будет отправлять problem через %s, recovery через %s и update через %s",
        PROBLEM_MEDIA_TYPE_NAME,
        SOLUTION_MEDIA_TYPE_NAME,
        UPDATE_MEDIA_TYPE_NAME,
    )


def main() -> int:
    configure_logging()
    try:
        args = parse_args()
        install(args)
    except (KeyboardInterrupt, EOFError):
        print("\nПрервано пользователем.", file=sys.stderr)
        return 130
    except Exception as error:
        logging.error("%s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
