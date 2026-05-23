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
        logger.info("Platform %s: section is not dict: %s", platform, section)
        return False
    required = _PLATFORM_REQUIRED_FIELDS.get(platform, [])
    missing = [f for f in required if not section.get(f)]
    if missing:
        logger.info("Platform %s: missing required fields: %s, section: %s", platform, missing, section)
    # All required fields must be present for the platform to be considered configured
    return all(section.get(f) for f in required)


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
    """Poll Feishu QR registration status (non-blocking).
    
    Returns immediately with current status, does not block waiting for completion.
    """
    try:
        from gateway.platforms.feishu import (
            _accounts_base_url,
            _REGISTRATION_PATH,
            _ONBOARD_REQUEST_TIMEOUT_S,
        )
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        from urllib.parse import urlencode
        import json
    except ImportError as exc:
        return {"ok": False, "error": str(exc)}
    
    try:
        base_url = _accounts_base_url("feishu")
        url = f"{base_url}{_REGISTRATION_PATH}"
        data = urlencode({
            "action": "poll",
            "device_code": device_code,
            "tp": "ob_app",
        }).encode("utf-8")
        req = Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        
        with urlopen(req, timeout=_ONBOARD_REQUEST_TIMEOUT_S) as resp:
            res = json.loads(resp.read().decode("utf-8"))
        
        # Check for success
        if res.get("client_id") and res.get("client_secret"):
            user_info = res.get("user_info") or {}
            tenant_brand = user_info.get("tenant_brand")
            domain = "lark" if tenant_brand == "lark" else "feishu"
            return {
                "ok": True,
                "status": "confirmed",
                "credentials": {
                    "app_id": res["client_id"],
                    "app_secret": res["client_secret"],
                    "domain": domain,
                },
            }
        
        # Check for terminal errors
        error = res.get("error", "")
        if error in {"access_denied", "expired_token"}:
            return {"ok": True, "status": "expired"}
        
        # Still pending
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
        # Encode aes_key into task_id for later decryption
        import base64
        combined = f"{task_id}:{base64.b64encode(aes_key.encode()).decode()}"
        return {
            "ok": True,
            "qr_data_url": qr_url,
            "task_id": combined,
            "expires_in": 600,
        }
    except Exception as exc:
        logger.exception("qqbot QR begin failed")
        return {"ok": False, "error": str(exc)}


def _qr_poll_qq(task_id: str) -> dict:
    """Poll QQBot QR registration status.

    task_id is the bind task_id from _qr_begin_qq (includes aes_key).
    """
    if not task_id:
        return {"ok": False, "error": "missing task_id"}

    try:
        from gateway.platforms.qqbot.onboard import (
            _poll_bind_result,
            BindStatus,
        )
        from gateway.platforms.qqbot.crypto import decrypt_secret
    except ImportError:
        return {"ok": False, "error": "qqbot module unavailable"}

    try:
        # Parse task_id and aes_key
        import base64
        if ":" in task_id:
            actual_task_id, aes_key_b64 = task_id.rsplit(":", 1)
            aes_key = base64.b64decode(aes_key_b64).decode()
        else:
            return {"ok": False, "error": "invalid task_id format"}

        status, app_id, encrypted_secret, user_openid = _poll_bind_result(
            actual_task_id, timeout=30
        )

        # Debug logging
        logger.info("QQ poll status: %s (value: %s), app_id: %s", status, int(status), app_id)

        if status == BindStatus.COMPLETED:
            client_secret = decrypt_secret(encrypted_secret, aes_key)
            return {
                "ok": True,
                "status": "confirmed",
                "credentials": {
                    "app_id": app_id,
                    "client_secret": client_secret,
                    "user_openid": user_openid,
                },
            }
        elif status == BindStatus.EXPIRED:
            return {"ok": True, "status": "expired"}

        return {"ok": True, "status": "pending"}
    except Exception as exc:
        logger.exception("QQ poll error: %s", exc)
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

    # Get configured platforms from config
    cfg_path = _get_config_path()
    cfg = _load_yaml_config_file(cfg_path)
    platform_names = []
    for p in sorted(_PLATFORMS):
        if _platform_configured(cfg, p):
            platform_names.append(p)

    if alive is True:
        running = True
        configured = True
    elif alive is False:
        running = False
        configured = True
    else:
        running = pid is not None
        # Gateway is configured if any platform is configured, regardless of running state
        configured = len(platform_names) > 0

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
        # Load .env file before starting gateway so subprocess inherits env vars
        try:
            from api.config import get_env_file_path
            env_path = get_env_file_path()
            if env_path and env_path.exists():
                env_text = env_path.read_text(encoding="utf-8")
                for line in env_text.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip()
                        # Only set if not already set (respect existing env)
                        if key and value and key not in os.environ:
                            os.environ[key] = value
        except Exception as e:
            logger.warning("Failed to preload .env for gateway start: %s", e)
        
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
        import subprocess
        result = subprocess.run(
            ["hermes", "gateway", "stop"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return j(handler, {"ok": True, "message": "Gateway stopping..."})
        logger.warning("hermes gateway stop failed (rc=%d, stderr=%s), falling back to SIGTERM",
                       result.returncode, result.stderr.strip())
        try:
            from gateway.status import get_running_pid
            pid = get_running_pid()
        except ImportError:
            pid = None
        if pid:
            os.kill(pid, signal.SIGTERM)
            return j(handler, {"ok": True, "message": "Gateway stopping..."})
        return j(handler, {"ok": False, "message": "Gateway not running"})
    except subprocess.TimeoutExpired:
        return j(handler, {"ok": False, "message": "Gateway stop timed out"})
    except Exception as exc:
        return j(handler, {"ok": False, "message": str(exc)})


def _handle_restart(handler) -> bool:
    try:
        import subprocess
        subprocess.run(
            ["hermes", "gateway", "stop"],
            capture_output=True, timeout=30,
        )
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
            except Exception:
                pass
    except Exception:
        pass
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


# Platform credential to env var mapping
_PLATFORM_ENV_MAPPING = {
    "feishu": {
        "app_id": "FEISHU_APP_ID",
        "app_secret": "FEISHU_APP_SECRET",
        "verification_token": "FEISHU_VERIFICATION_TOKEN",
        "encrypt_key": "FEISHU_ENCRYPT_KEY",
    },
    "wecom": {
        "bot_id": "WECOM_BOT_ID",
        "secret": "WECOM_SECRET",
    },
    "weixin": {
        "token": "WEIXIN_TOKEN",
        "account_id": "WEIXIN_ACCOUNT_ID",
    },
    "qqbot": {
        "app_id": "QQ_APP_ID",
        "client_secret": "QQ_CLIENT_SECRET",
    },
    "dingtalk": {
        "client_id": "DINGTALK_CLIENT_ID",
        "client_secret": "DINGTALK_CLIENT_SECRET",
    },
}


def _update_env_file(platform: str, credentials: dict) -> None:
    """Sync platform credentials to ~/.hermes/.env file."""
    try:
        from api.config import get_env_file_path
        env_path = get_env_file_path()
        logger.info("Updating .env for platform %s, credentials: %s, env_path: %s", platform, credentials, env_path)
        if not env_path:
            logger.warning("No env_path returned")
            return
        
        # Read existing .env content
        env_lines = []
        if env_path.exists():
            env_lines = env_path.read_text(encoding="utf-8").splitlines()
            logger.info("Existing .env has %d lines", len(env_lines))
        
        # Build a set of existing keys for quick lookup
        existing_keys = set()
        for line in env_lines:
            if "=" in line and not line.strip().startswith("#"):
                key = line.split("=", 1)[0].strip()
                existing_keys.add(key)
        
        # Add new credential lines
        env_mapping = _PLATFORM_ENV_MAPPING.get(platform, {})
        logger.info("Env mapping for %s: %s", platform, env_mapping)
        for field, value in credentials.items():
            env_var = env_mapping.get(field)
            logger.info("Field %s -> env_var %s = %s", field, env_var, "[SET]" if (env_var and value) else "[SKIP]")
            if env_var and value:
                # Remove existing line for this var if present
                env_lines = [line for line in env_lines if not line.strip().startswith(f"{env_var}=")]
                # Add new line
                env_lines.append(f"{env_var}={value}")
        
        # Write back
        env_content = "\n".join(env_lines)
        if env_lines and not env_content.endswith("\n"):
            env_content += "\n"
        env_path.write_text(env_content, encoding="utf-8")
        logger.info("Wrote .env file with %d lines", len(env_lines))
        
        # Update current process environment
        for field, value in credentials.items():
            env_var = env_mapping.get(field)
            if env_var and value:
                os.environ[env_var] = value
    except Exception as e:
        logger.warning("Failed to update .env file: %s", e)


def _handle_channel_update(handler, platform: str, body: dict = None) -> bool:
    if body is None:
        body = _read_body(handler)
    logger.info("Channel update for %s, body: %s", platform, body)
    cfg = _load_yaml_config_file(_get_config_path())
    section = cfg.get(platform, {})
    if not isinstance(section, dict):
        section = {}
    
    # Handle enabled flag
    if "enabled" in body:
        section["enabled"] = bool(body["enabled"])
    
    # Platform-specific field handling
    credentials_to_sync = {}
    
    if platform == "weixin":
        # Weixin fields: token, account_id
        for field in ["token", "account_id"]:
            if field in body:
                val = (body[field] or "").strip()
                if val:
                    section[field] = val
                    credentials_to_sync[field] = val
                    logger.info("Weixin: saved %s", field)
    
    elif platform == "wecom":
        # WeCom fields: bot_id, secret
        for field in ["bot_id", "secret"]:
            if field in body:
                val = (body[field] or "").strip()
                if val:
                    section[field] = val
                    credentials_to_sync[field] = val
                    logger.info("WeCom: saved %s", field)
    
    elif platform == "feishu":
        # Feishu fields: app_id, app_secret, verification_token
        for field in ["app_id", "app_secret", "verification_token"]:
            if field in body:
                val = (body[field] or "").strip()
                if val:
                    section[field] = val
                    credentials_to_sync[field] = val
                    logger.info("Feishu: saved %s", field)
    
    elif platform == "qqbot":
        # QQBot fields: app_id, client_secret
        for field in ["app_id", "client_secret"]:
            if field in body:
                val = (body[field] or "").strip()
                if val:
                    section[field] = val
                    credentials_to_sync[field] = val
                    logger.info("QQBot: saved %s", field)
    
    elif platform == "dingtalk":
        # DingTalk fields: client_id, client_secret
        for field in ["client_id", "client_secret"]:
            if field in body:
                val = (body[field] or "").strip()
                if val:
                    section[field] = val
                    credentials_to_sync[field] = val
                    logger.info("DingTalk: saved %s", field)
    
    logger.info("Final section for %s: %s", platform, section)
    cfg[platform] = section
    _save_config(cfg)
    
    # Sync credentials to .env file
    if credentials_to_sync:
        logger.info("Syncing to .env for %s: %s", platform, credentials_to_sync)
        _update_env_file(platform, credentials_to_sync)
    
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
    
    # Also clear credentials from .env
    try:
        from api.config import get_env_file_path
        env_path = get_env_file_path()
        if env_path and env_path.exists():
            env_lines = env_path.read_text(encoding="utf-8").splitlines()
            env_mapping = _PLATFORM_ENV_MAPPING.get(platform, {})
            env_vars_to_remove = set(env_mapping.values())
            env_lines = [line for line in env_lines if not any(line.strip().startswith(f"{var}=") for var in env_vars_to_remove)]
            env_content = "\n".join(env_lines)
            if env_lines and not env_content.endswith("\n"):
                env_content += "\n"
            env_path.write_text(env_content, encoding="utf-8")
    except Exception as e:
        logger.warning("Failed to clear .env credentials: %s", e)
    
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
        if handler.command == "PUT" or handler.command == "POST":
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
