import json
import logging
import os
import re
import signal
import shutil
import uuid
import asyncio
import threading
from urllib.parse import parse_qs
from pathlib import Path

from api.agent_health import build_agent_health_payload
from api.config import (
    _get_config_path,
    _load_yaml_config_file,
    _save_yaml_config_file,
    reload_config,
)
from api.helpers import bad, j

HERMES_HOME = str(Path(__file__).resolve().parent.parent.parent)

logger = logging.getLogger(__name__)

_PLATFORMS = frozenset({"feishu", "dingtalk", "weixin", "wecom", "qqbot"})

_PLATFORM_REQUIRED_FIELDS = {
    "feishu": ["app_id", "app_secret"],
    "dingtalk": ["client_id", "client_secret"],
    "weixin": ["token"],
    "wecom": ["bot_id", "secret"],
    "qqbot": ["app_id", "client_secret"],
}


def _read_body(handler) -> dict:
    length = int(handler.headers.get("Content-Length", 0))
    if length == 0:
        return {}
    return json.loads(handler.rfile.read(length))


def _platform_configured(cfg: dict, platform: str) -> bool:
    section = cfg.get(platform, {})
    if not isinstance(section, dict):
        return False
    required = _PLATFORM_REQUIRED_FIELDS.get(platform, [])
    return any(section.get(f) for f in required)


def _extract_platform(path: str) -> tuple[str | None, str]:
    m = re.match(
        r"^/api/gateway/channels/(feishu|dingtalk|weixin|wecom|qqbot)(/.*)?$", path
    )
    if m:
        return m.group(1), m.group(2) or ""
    return None, ""


def _save_config(data: dict) -> None:
    cfg_path = _get_config_path()
    try:
        shutil.copy2(cfg_path, cfg_path.with_suffix(".yaml.bak"))
    except OSError:
        logger.warning("config backup failed")
    _save_yaml_config_file(cfg_path, data)
    reload_config()


def _qr_begin_feishu() -> dict:
    try:
        from gateway.platforms.feishu import _begin_registration
    except ImportError as exc:
        return {"ok": False, "error": f"feishu module unavailable: {exc}"}
    try:
        result = _begin_registration("feishu")
        return {
            "ok": True,
            "qr_data_url": result.get("qr_url", ""),
            "device_code": result.get("device_code", ""),
            "task_id": str(uuid.uuid4()),
            "expires_in": result.get("expire_in", 600),
        }
    except Exception as exc:
        logger.exception("feishu QR begin failed")
        return {"ok": False, "error": str(exc)}


def _qr_begin_wecom() -> dict:
    try:
        from gateway.platforms.wecom import _QR_GENERATE_URL
    except ImportError:
        return {"ok": False, "error": "wecom module unavailable"}
    try:
        import urllib.request

        req = urllib.request.Request(
            f"{_QR_GENERATE_URL}?source=hermes",
            headers={"User-Agent": "HermesAgent/1.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        data = raw.get("data") or {}
        auth_url = data.get("auth_url", "")
        scode = data.get("scode", "")
        if not auth_url:
            return {"ok": False, "error": "wecom did not return auth_url"}
        if not scode:
            return {"ok": False, "error": "wecom did not return scode"}
        return {
            "ok": True,
            "qr_data_url": auth_url,
            "task_id": scode,  # Use scode as task_id for polling
            "expires_in": 300,
        }
    except Exception as exc:
        logger.exception("wecom QR begin failed")
        return {"ok": False, "error": str(exc)}


def _qr_poll_wecom(task_id: str) -> dict:
    """Poll WeCom QR scan status.

    task_id here is actually the scode from _qr_begin_wecom.
    """
    if not task_id:
        return {"ok": False, "error": "missing task_id (scode)"}

    try:
        from gateway.platforms.wecom import _QR_QUERY_URL
    except ImportError:
        return {"ok": False, "error": "wecom module unavailable"}

    try:
        import urllib.request
        import urllib.parse

        query_url = f"{_QR_QUERY_URL}?scode={urllib.parse.quote(task_id)}"
        req = urllib.request.Request(query_url, headers={"User-Agent": "HermesAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        result_data = result.get("data") or {}
        status = str(result_data.get("status") or "").lower()

        if status == "success":
            bot_info = result_data.get("bot_info") or {}
            bot_id = str(bot_info.get("botid") or bot_info.get("bot_id") or "").strip()
            secret = str(bot_info.get("secret") or "").strip()
            if bot_id and secret:
                return {
                    "ok": True,
                    "status": "confirmed",
                    "credentials": {
                        "bot_id": bot_id,
                        "secret": secret,
                    },
                }
            return {
                "ok": True,
                "status": "pending",
                "message": "Scan reported success but credentials incomplete",
            }

        return {"ok": True, "status": "pending"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _qr_poll_feishu(device_code: str) -> dict:
    try:
        from gateway.platforms.feishu import _poll_registration
    except ImportError as exc:
        return {"ok": False, "error": str(exc)}
    try:
        result = _poll_registration(device_code=device_code, interval=5, expire_in=600)
        if result:
            return {
                "ok": True,
                "status": "confirmed",
                "credentials": {
                    "app_id": result.get("app_id", ""),
                    "app_secret": result.get("app_secret", ""),
                    "domain": result.get("domain", "feishu"),
                },
            }
        return {"ok": True, "status": "pending"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _qr_begin_weixin() -> dict:
    """Start Weixin QR login flow via the internal iLink API.

    Returns {"ok": True, "qr_data_url": url, "task_id": str, "expires_in": 480}
    or {"ok": False, "error": msg}.

    NOTE: weixin.qr_login() runs the full async flow (create → poll → confirm)
    in one blocking call.  For the web UI API we need to *split* this into:
    1) _qr_begin_weixin: create QR, return URL + task_id
    2) _qr_poll_weixin: poll status using the qrcode_value from step 1

    We call the internal _api_get/_make_ssl_connector directly.
    """
    try:
        from gateway.platforms.weixin import (
            ILINK_BASE_URL,
            EP_GET_BOT_QR,
            EP_GET_QR_STATUS,
            QR_TIMEOUT_MS,
            _api_get,
            _make_ssl_connector,
        )
    except ImportError as exc:
        return {"ok": False, "error": f"weixin module unavailable: {exc}"}

    try:
        import aiohttp

        async def _get_qr():
            """Create a QR code and return (qrcode_url, qrcode_value)."""
            try:
                async with aiohttp.ClientSession(
                    trust_env=True, connector=_make_ssl_connector()
                ) as session:
                    qr_resp = await _api_get(
                        session,
                        base_url=ILINK_BASE_URL,
                        endpoint=f"{EP_GET_BOT_QR}?bot_type=3",
                        timeout_ms=QR_TIMEOUT_MS,
                    )
                qrcode_url = str(qr_resp.get("qrcode_img_content") or "")
                qrcode_value = str(qr_resp.get("qrcode") or "")
                if not qrcode_url and not qrcode_value:
                    return None, None, "QR response missing qrcode fields"
                return qrcode_url or qrcode_value, qrcode_value, None
            except Exception as exc:
                return None, None, str(exc)

        qr_url, qrcode_value, error = asyncio.run(_get_qr())
        if error:
            logger.error("weixin QR begin failed: %s", error)
            return {"ok": False, "error": error}

        return {
            "ok": True,
            "qr_data_url": qr_url,
            "task_id": qrcode_value,  # use qrcode_value as task_id for polling
            "expires_in": 480,
        }
    except Exception as exc:
        logger.exception("weixin QR begin failed")
        return {"ok": False, "error": str(exc)}


def _qr_poll_weixin(task_id: str) -> dict:
    """Poll Weixin QR login status.

    task_id here is actually the qrcode_value from _qr_begin_weixin.
    """
    if not task_id:
        return {"ok": False, "error": "missing task_id (qrcode_value)"}

    try:
        from gateway.platforms.weixin import (
            ILINK_BASE_URL,
            EP_GET_QR_STATUS,
            QR_TIMEOUT_MS,
            _api_get,
            _make_ssl_connector,
        )
    except ImportError:
        return {"ok": False, "error": "weixin module unavailable"}

    try:
        import aiohttp

        async def _poll():
            try:
                async with aiohttp.ClientSession(
                    trust_env=True, connector=_make_ssl_connector()
                ) as session:
                    status_resp = await _api_get(
                        session,
                        base_url=ILINK_BASE_URL,
                        endpoint=f"{EP_GET_QR_STATUS}?qrcode={task_id}",
                        timeout_ms=QR_TIMEOUT_MS,
                    )
                status = str(status_resp.get("status") or "wait")
                if status == "confirmed":
                    account_id = str(status_resp.get("ilink_bot_id") or "")
                    token = str(status_resp.get("bot_token") or "")
                    base_url = str(status_resp.get("baseurl") or ILINK_BASE_URL)
                    user_id = str(status_resp.get("ilink_user_id") or "")
                    return {
                        "ok": True,
                        "status": "confirmed",
                        "credentials": {
                            "account_id": account_id,
                            "token": token,
                            "base_url": base_url,
                            "user_id": user_id,
                        },
                    }
                return {"ok": True, "status": status}
            except Exception as exc:
                return {"ok": False, "status": "error", "error": str(exc)}

        return asyncio.run(_poll())
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _qr_begin_qq() -> dict:
    """Start QQBot QR registration flow.

    Returns {"ok": True, "qr_data_url": url, "task_id": str, "expires_in": 600}
    or {"ok": False, "error": msg}.
    """
    try:
        from gateway.platforms.qqbot.onboard import (
            _create_bind_task,
            build_connect_url,
        )
    except ImportError as exc:
        return {"ok": False, "error": f"qqbot module unavailable: {exc}"}

    try:
        task_id, aes_key = _create_bind_task(timeout=30)
        qr_url = build_connect_url(task_id)
        return {
            "ok": True,
            "qr_data_url": qr_url,
            "task_id": task_id,
            "expires_in": 600,
        }
    except Exception as exc:
        logger.exception("qqbot QR begin failed")
        return {"ok": False, "error": str(exc)}


def _qr_poll_qq(task_id: str) -> dict:
    """Poll QQBot QR registration status.

    task_id is the bind task_id from _qr_begin_qq.
    """
    if not task_id:
        return {"ok": False, "error": "missing task_id"}

    try:
        from gateway.platforms.qqbot.onboard import (
            _poll_bind_result,
            BindStatus,
        )
        from gateway.platforms.qqbot.crypto import decrypt_secret, generate_bind_key
    except ImportError:
        return {"ok": False, "error": "qqbot module unavailable"}

    try:
        status, app_id, encrypted_secret, user_openid = _poll_bind_result(
            task_id, timeout=600
        )

        if status == BindStatus.COMPLETED:
            client_secret = decrypt_secret(encrypted_secret, generate_bind_key())
            return {
                "ok": True,
                "status": "confirmed",
                "credentials": {
                    "app_id": app_id,
                    "client_secret": client_secret,
                    "user_openid": user_openid,
                },
            }

        return {"ok": True, "status": "pending"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ── Route handlers ──────────────────────────────────────────────────────


def _handle_status(handler) -> bool:
    health = build_agent_health_payload()
    alive = health.get("alive")

    pid = None
    uptime = None
    try:
        from gateway.status import get_running_pid, read_runtime_status

        pid = get_running_pid()
        status_data = read_runtime_status()
        if status_data and pid:
            started = status_data.get("started_at")
            if started:
                import datetime
                try:
                    delta = datetime.datetime.now(datetime.timezone.utc) - started
                    uptime = int(delta.total_seconds())
                except Exception:
                    pass
    except ImportError:
        pass

    if alive is True:
        running = True
        configured = True
    elif alive is False:
        running = False
        configured = True
    else:
        running = pid is not None
        configured = bool(pid)

    cfg_path = _get_config_path()
    cfg = _load_yaml_config_file(cfg_path)
    platform_names = []
    for p in sorted(_PLATFORMS):
        if _platform_configured(cfg, p):
            platform_names.append(p)

    return j(handler, {
        "ok": True,
        "running": running,
        "configured": configured,
        "pid": pid,
        "uptime_seconds": uptime,
        "platforms": platform_names,
    })


def _handle_start(handler) -> bool:
    try:
        import subprocess
        proc = subprocess.Popen(
            ["hermes", "gateway", "start"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return j(handler, {"ok": True, "message": "Gateway starting..."})
    except Exception as exc:
        return j(handler, {"ok": False, "message": f"Failed to start gateway: {exc}"})


def _handle_stop(handler) -> bool:
    try:
        from gateway.status import get_running_pid
        pid = get_running_pid()
    except ImportError:
        pid = None
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            return j(handler, {"ok": True, "message": "Gateway stopping..."})
        except ProcessLookupError:
            return j(handler, {"ok": True, "message": "Gateway was not running"})
        except Exception as exc:
            return j(handler, {"ok": False, "message": str(exc)})
    return j(handler, {"ok": False, "message": "Gateway not running"})


def _handle_restart(handler) -> bool:
    try:
        from gateway.status import get_running_pid
        pid = get_running_pid()
    except ImportError:
        pid = None
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception as exc:
            return j(handler, {"ok": False, "message": str(exc)})
    try:
        import subprocess
        subprocess.Popen(
            ["hermes", "gateway", "start"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return j(handler, {"ok": True, "message": "Gateway restarting..."})
    except Exception as exc:
        return j(handler, {"ok": False, "message": str(exc)})


def _handle_channels_list(handler) -> bool:
    cfg = _load_yaml_config_file(_get_config_path())
    channels = {}
    for p in sorted(_PLATFORMS):
        section = cfg.get(p, {})
        channels[p] = {
            "enabled": bool(section.get("enabled", False)) if isinstance(section, dict) else False,
            "configured": _platform_configured(cfg, p),
        }
    return j(handler, {"ok": True, "channels": channels})


def _handle_channel_update(handler, platform: str, body: dict = None) -> bool:
    if body is None:
        body = _read_body(handler)
    cfg = _load_yaml_config_file(_get_config_path())
    section = cfg.get(platform, {})
    if not isinstance(section, dict):
        section = {}
    for key in body:
        if key == "enabled":
            section["enabled"] = bool(body[key])
        elif key in _PLATFORM_REQUIRED_FIELDS.get(platform, []):
            val = (body[key] or "").strip()
            if val:
                section[key] = val
        elif key in {"verification_token", "bot_id", "token", "client_id", "client_secret", "app_id", "app_secret"}:
            val = (body[key] or "").strip()
            if val:
                section[key] = val
    cfg[platform] = section
    _save_config(cfg)
    return j(handler, {"ok": True})


def _handle_channel_test(handler, platform: str) -> bool:
    cfg = _load_yaml_config_file(_get_config_path())
    section = cfg.get(platform, {})
    if not isinstance(section, dict):
        return j(handler, {"ok": False, "message": f"{platform} is not configured"})
    required = _PLATFORM_REQUIRED_FIELDS.get(platform, [])
    missing = [f for f in required if not section.get(f)]
    if missing:
        return j(handler, {
            "ok": False,
            "message": f"Missing required fields: {', '.join(missing)}",
        })
    return j(handler, {"ok": True, "message": "Configuration looks valid"})


def _handle_channel_clear(handler, platform: str) -> bool:
    cfg = _load_yaml_config_file(_get_config_path())
    cfg[platform] = {"enabled": False}
    _save_config(cfg)
    return j(handler, {"ok": True})


def _handle_channel_qr_begin(handler, platform: str) -> bool:
    if platform == "feishu":
        result = _qr_begin_feishu()
        return j(handler, result)
    elif platform == "wecom":
        result = _qr_begin_wecom()
        return j(handler, result)
    elif platform == "weixin":
        result = _qr_begin_weixin()
        return j(handler, result)
    elif platform == "qqbot":
        result = _qr_begin_qq()
        return j(handler, result)
    else:
        return j(handler, {
            "ok": False,
            "error": f"QR onboarding not yet implemented for {platform}",
            "hint": "Use manual configuration instead",
        })


def _handle_channel_qr_poll(handler, platform: str, body: dict = None) -> bool:
    if body is None:
        body = _read_body(handler)
    task_id = body.get("task_id", "")
    device_code = body.get("device_code", "")
    if platform == "feishu" and device_code:
        return j(handler, _qr_poll_feishu(device_code))
    elif platform == "wecom" and task_id:
        return j(handler, _qr_poll_wecom(task_id))
    elif platform == "weixin" and task_id:
        return j(handler, _qr_poll_weixin(task_id))
    elif platform == "qqbot" and task_id:
        return j(handler, _qr_poll_qq(task_id))
    return j(handler, {"ok": True, "status": "pending"})




# ── Public dispatcher ───────────────────────────────────────────────────


def handle_gateway_api(handler, parsed, body: dict = None) -> bool:
    path = parsed.path

    if path == "/api/gateway/status" and handler.command == "GET":
        return _handle_status(handler)

    if path == "/api/gateway/start" and handler.command == "POST":
        return _handle_start(handler)

    if path == "/api/gateway/stop" and handler.command == "POST":
        return _handle_stop(handler)

    if path == "/api/gateway/restart" and handler.command == "POST":
        return _handle_restart(handler)

    if path == "/api/gateway/channels" and handler.command == "GET":
        return _handle_channels_list(handler)

    platform, subpath = _extract_platform(path)
    if platform is None:
        return False

    if subpath == "" or subpath == "/":
        if handler.command == "GET":
            return _handle_channels_list(handler)
        if handler.command == "PUT":
            return _handle_channel_update(handler, platform, body)
        return False

    if subpath == "/test" and handler.command == "POST":
        return _handle_channel_test(handler, platform)

    if subpath == "/clear" and handler.command == "POST":
        return _handle_channel_clear(handler, platform)

    if subpath == "/qr/begin" and handler.command == "POST":
        return _handle_channel_qr_begin(handler, platform)

    if subpath == "/qr/poll" and handler.command == "POST":
        return _handle_channel_qr_poll(handler, platform, body)

    return False
