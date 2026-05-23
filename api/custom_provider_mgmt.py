"""
Hermes Web UI -- Custom Provider Management API.
"""
import json
from api.config import (
    _get_config_path,
    _load_yaml_config_file,
    _save_yaml_config_file,
    reload_config,
    invalidate_models_cache,
    _custom_provider_entries
)
from api.helpers import j, bad


def handle_custom_providers_api(handler, parsed, body=None) -> bool:
    """
    Dispatcher for /api/custom-providers/* routes.
    Returns True if route matched, False otherwise.

    When ``body`` is already parsed (e.g. from ``handle_post`` where
    ``read_body()`` consumed the request stream) it is used for POST/PUT
    handlers instead of re-reading from ``handler.rfile``.
    """
    path = parsed.path
    method = handler.command

    if path == '/api/custom-providers':
        if method == 'POST':
            return handle_post_custom_providers(handler, body)
        elif method == 'PUT':
            return handle_put_custom_providers(handler, body)
        elif method == 'GET':
            return handle_get_custom_providers(handler)
        elif method == 'DELETE':
            return handle_delete_custom_providers(handler)
        else:
            return False
    elif path == '/api/custom-providers/probe':
        if method == 'POST':
            return handle_post_custom_providers_probe(handler, body)
        else:
            return False
    else:
        return False


def handle_get_custom_providers(handler) -> bool:
    """GET /api/custom-providers -> list all custom providers (without api_key)."""
    config_path = _get_config_path()
    data = _load_yaml_config_file(config_path)
    providers = data.get("custom_providers", [])
    # Remove api_key from each provider for safety
    safe_providers = []
    for p in providers:
        safe_p = p.copy()
        safe_p.pop("api_key", None)
        safe_providers.append(safe_p)
    j(handler, {"ok": True, "providers": safe_providers})
    return True


def handle_post_custom_providers(handler, body=None) -> bool:
    """POST /api/custom-providers -> create a new custom provider."""
    if body is None:
        # Fallback for GET-path invocation (body was not pre-parsed)
        length = int(handler.headers.get('Content-Length', 0))
        if length == 0:
            return bad(handler, "Empty body")
        try:
            body = json.loads(handler.rfile.read(length))
        except json.JSONDecodeError:
            return bad(handler, "Invalid JSON")

    # Validate required fields
    required = ["name", "base_url", "api_key", "model"]
    for field in required:
        if not body.get(field):
            return bad(handler, f"Missing required field: {field}")

    name = body["name"].strip()
    base_url = body["base_url"].strip()
    api_key = body["api_key"].strip()
    model = body["model"].strip()

    if not name or not base_url or not api_key or not model:
        return bad(handler, "Fields cannot be empty")

    config_path = _get_config_path()
    data = _load_yaml_config_file(config_path)
    # Ensure custom_providers list exists
    if "custom_providers" not in data:
        data["custom_providers"] = []

    # Check for duplicate name
    for p in data["custom_providers"]:
        if p.get("name") == name:
            return bad(handler, f"Provider with name '{name}' already exists")

    # Add new provider
    new_provider = {
        "name": name,
        "base_url": base_url,
        "api_key": api_key,
        "model": model
    }
    data["custom_providers"].append(new_provider)

    # Backup and save
    import shutil
    shutil.copy2(config_path, config_path.with_suffix('.yaml.bak'))
    _save_yaml_config_file(config_path, data)
    reload_config()
    invalidate_models_cache()

    j(handler, {"ok": True, "provider": new_provider})
    return True


def handle_put_custom_providers(handler, body=None) -> bool:
    """PUT /api/custom-providers -> update existing custom provider."""
    if body is None:
        length = int(handler.headers.get('Content-Length', 0))
        if length == 0:
            return bad(handler, "Empty body")
        try:
            body = json.loads(handler.rfile.read(length))
        except json.JSONDecodeError:
            return bad(handler, "Invalid JSON")

    # Validate required fields
    required = ["name", "base_url", "api_key", "model"]
    for field in required:
        if not body.get(field):
            return bad(handler, f"Missing required field: {field}")

    name = body["name"].strip()
    base_url = body["base_url"].strip()
    api_key = body["api_key"].strip()
    model = body["model"].strip()

    if not name:
        return bad(handler, "Provider name cannot be empty")

    config_path = _get_config_path()
    data = _load_yaml_config_file(config_path)
    # Ensure custom_providers list exists
    if "custom_providers" not in data:
        data["custom_providers"] = []

    # Find provider by name
    found = False
    for p in data["custom_providers"]:
        if p.get("name") == name:
            found = True
            # Update fields
            p["base_url"] = base_url
            p["model"] = model
            # Only update api_key if non-empty (to allow clearing only if explicitly set?)
            # But instructions: if api_key is empty string, keep existing key
            if api_key != "":
                p["api_key"] = api_key
            break

    if not found:
        return bad(handler, f"Provider with name '{name}' not found")

    # Backup and save
    import shutil
    shutil.copy2(config_path, config_path.with_suffix('.yaml.bak'))
    _save_yaml_config_file(config_path, data)
    reload_config()
    invalidate_models_cache()

    j(handler, {"ok": True})
    return True


def handle_delete_custom_providers(handler) -> bool:
    """DELETE /api/custom-providers?name=xxx -> delete custom provider by name."""
    from urllib.parse import parse_qs
    query_str = parsed.query if hasattr(parsed, 'query') else ''
    if isinstance(query_str, bytes):
        query_str = query_str.decode('utf-8')
    params = parse_qs(query_str)
    name = (params.get('name', [''])[0] or '').strip()
    if not name:
        return bad(handler, "Missing 'name' parameter")

    config_path = _get_config_path()
    data = _load_yaml_config_file(config_path)
    # Ensure custom_providers list exists
    if "custom_providers" not in data:
        data["custom_providers"] = []

    # Find and remove provider by name
    original_len = len(data["custom_providers"])
    data["custom_providers"] = [
        p for p in data["custom_providers"]
        if p.get("name") != name
    ]
    if len(data["custom_providers"]) == original_len:
        return bad(handler, f"Provider with name '{name}' not found")

    # Backup and save
    import shutil
    shutil.copy2(config_path, config_path.with_suffix('.yaml.bak'))
    _save_yaml_config_file(config_path, data)
    reload_config()
    invalidate_models_cache()

    j(handler, {"ok": True})
    return True


def handle_post_custom_providers_probe(handler, body=None) -> bool:
    """POST /api/custom-providers/probe -> probe for available models."""
    if body is None:
        length = int(handler.headers.get('Content-Length', 0))
        if length == 0:
            return bad(handler, "Empty body")
        try:
            body = json.loads(handler.rfile.read(length))
        except json.JSONDecodeError:
            return bad(handler, "Invalid JSON")

    base_url = body.get("base_url", "").strip()
    api_key = body.get("api_key", "").strip()

    if not base_url:
        return bad(handler, "base_url is required")

    from api.onboarding import probe_provider_endpoint
    result = probe_provider_endpoint("custom", base_url, api_key)
    j(handler, result)
    return True