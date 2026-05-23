# Custom Provider & Gateway Channel Configuration UI

Design document for two new configuration UIs in Hermes WebUI: **Custom
Providers** (name + base\_url + api\_key + model) and **Gateway Channels**
(飞书/钉钉/微信/企业微信/QQ 平台的启用、配置与解绑).

## Goals

1. Allow users to add/edit/delete custom API providers from the WebUI without
   editing `config.yaml` by hand.
2. Allow users to configure, enable/disable, test, and unlink messaging gateway
   channels from the WebUI.
3. Minimise changes to existing files to reduce `git merge` conflicts with
   upstream.

## Non-goals

- Replacing the existing onboarding wizard or CLI provider setup.
- Storing credentials outside `config.yaml` (they live in the same file).
- QR code onboarding for channels that don't support it (DingTalk).

## 1. Custom Providers

### Location

Inside the existing **Providers** panel (`static/panels.js` →
`loadProvidersPanel()`), as a new "Custom Providers" section separated by a
visual divider at the bottom.

### Interaction

| Action | Behaviour |
|---|---|
| **Add** | CTA button "Add Custom Provider" at the bottom of the section |
| **Edit** | Click the provider row/entry → opens the same dialog pre-filled |
| **Delete** | Click delete icon → confirm → remove from `config.yaml` |

Add / Edit use a **modal dialog** (`showCustomProviderDialog`) with these
fields:

| Field | Type | Behaviour |
|---|---|---|
| `name` | text input | Required. A short label (e.g. `my-ollama`). |
| `base_url` | URL input | Required. The endpoint base URL. |
| `api_key` | password input | Required. API key, masked. |
| `model` | combobox | Autofilled + manually editable. On base\_url + api\_key change, the UI automatically calls `/v1/models` on the endpoint and populates the dropdown. The user can also type any model name. |

### Storage

Saved to `config.yaml` under the top-level `custom_providers` key as a list:

```yaml
custom_providers:
  - name: my-ollama
    base_url: http://localhost:11434/v1
    api_key: ollama
    model: llama3
  - name: my-togetherai
    base_url: https://api.together.xyz/v1
    api_key: sk-tog-…
    model: mixtral-8x7b-32768
```

### Save mechanism

`_save_yaml_config_file()` → `reload_config()` → `invalidate_models_cache()`,
following the existing pattern. Before writing, the current `config.yaml` is
copied to `config.yaml.bak` (overwrites previous backup).

### Relevant existing code

| File | Purpose |
|---|---|
| `api/config.py` | `_save_yaml_config_file()` (line ~372), `get_available_models()` (line ~2652), custom\_providers reading (line ~814–820) |
| `api/providers.py` | `get_providers()` (line ~1732), custom provider reading (line ~1946–1980) |
| `api/routes.py` | Model/provider routes (line ~3508–3542) |
| `api/onboarding.py` | `probe_provider_endpoint()` (line ~355) — reusable for model detection |
| `static/ui.js` | `populateModelDropdown()` (line ~894) |
| `static/panels.js` | `loadProvidersPanel()` (line ~5736), `_buildProviderCard()` (line ~6036) |

### Implementation plan

**New files:**
- `api/custom_provider_mgmt.py` — backend CRUD + model detection endpoint
- `static/custom-providers.js` — frontend dialog + list + interactions

**Minimal edits to existing files:**
- `api/routes.py` — register routes (~10 lines)
- `static/panels.js` — add section to Providers panel (~5 lines)
- `static/index.html` — include new JS (1 line)

---

## 2. Gateway Channels

### Location

A new **Gateway Channels** panel in the sidebar, independent from Providers.
The existing read-only Gateway Status card (currently in System settings tab) moves
here and is replaced with full start/stop/restart controls.

### Panel layout

```
┌──────────────────────────────────────┐
│  Gateway                             │
│  ● Running ─── [Restart] [Stop]      │  ← process control header
│  Started: 2h ago · PID: 12345        │
├──────────────────────────────────────┤
│  Platforms                           │
│                                      │
│  ┌── 飞书 ──────────────────────┐   │
│  │  ● 已配置 ✓         [ON/OFF] │   │  ← per-platform cards
│  │  [测试连接] [重新配置] [清除] │   │
│  └──────────────────────────────┘   │
│  ┌── 钉钉 ──────────────────────┐   │
│  │  ○ 未配置                     │   │
│  │  [手动输入]                   │   │
│  └──────────────────────────────┘   │
│  ...                                │
└──────────────────────────────────────┘
```

### Platforms

| Platform | QR onboarding | Config fields |
|---|---|---|
| 飞书 (Feishu) | ✅ `feishu.qr_register()` → `qr_url` | `app_id`, `app_secret`, `verification_token` |
| 微信 (Weixin) | ✅ `weixin.qr_login()` → `qrcode_img_content` | `token` |
| 企业微信 (WeCom) | ✅ `wecom.qr_scan_for_bot_info()` → `auth_url` | `corp_id`, `agent_id`, `secret`, `token` |
| QQ | ✅ `qqbot.onboard.qr_register()` → connect URL | `app_id`, `client_secret` |
| 钉钉 (DingTalk) | ❌ No QR flow | `client_id`, `client_secret` |

### Card states per platform

| State | Visual | Actions |
|---|---|---|
| **Unconfigured** (QR capable) | Platform icon + name + "未配置" badge | Two buttons: **① 扫码配置** (QR wizard) **② 手动输入** (form) |
| **Unconfigured** (DingTalk) | Platform icon + name + "未配置" badge | One button: **手动输入** (form) |
| **Configured** | Platform icon + name + "已配置 ✓" badge + enable/disable toggle | **测试连接**, **重新配置**, **清除配置** |
| **Enabled** | Toggle ON, normal appearance | — |
| **Disabled** | Toggle OFF, dimmed appearance | — |

### Security

When a channel is **configured**, its credential fields are **never displayed**
in the UI. The card shows only the "已配置 ✓" status. To see or change
credentials, the user must use **清除配置** (clears all credentials, returns to
unconfigured state) or **重新配置** (re-runs QR wizard or re-opens the manual
form).

### QR onboarding flow

1. User clicks "扫码配置" on an unconfigured platform card.
2. Backend calls the platform's QR generation API:
   - Feishu → `feishu._begin_registration()` → `qr_url`
   - Weixin → `weixin._api_get(/ilink/bot/get_bot_qrcode)` → `qrcode_img_content`
   - WeCom → `wecom.qr_scan_for_bot_info()` → `auth_url`
   - QQ → `qqbot.onboard._create_bind_task()` + `build_connect_url()` → connect URL
3. Backend generates a QR code image (PNG) from the URL using the `qrcode` Python
   library and returns it to the frontend.
4. Frontend displays the QR code image in a modal/overlay, alongside:
   - The raw URL (as a clickable/text fallback)
   - A "已扫码, 请在手机上确认..." polling status indicator
   - A timeout / "二维码已过期, 请刷新" message with retry
5. Backend polls the platform's scan status endpoint until:
   - Confirmed → saves credentials to `config.yaml`, closes modal, updates card to "已配置 ✓"
   - Expired → returns error, user can retry
   - Denied → returns error

### Manual input flow

For platforms that support QR, the user may also choose "手动输入" instead.
This opens a form with the platform's credential fields. After filling and
submitting:

1. Credentials are saved to `config.yaml` under the platform's top-level key.
2. The card updates to "已配置 ✓".
3. A "测试连接" option becomes available.

### Gateway process control

The panel header shows current gateway status and provides start/stop/restart
buttons. Backend calls spawn/kill the gateway process (the same binary that
`hermes gateway start` launches).

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/gateway/status` | GET | Get gateway process status (already exists) |
| `/api/gateway/start` | POST | Start gateway process |
| `/api/gateway/stop` | POST | Stop gateway process (SIGTERM) |
| `/api/gateway/restart` | POST | Stop then start |

Existing code reference — the gateway is started via:

```python
from gateway.run import start_gateway
asyncio.run(start_gateway())
```

(ref: `scripts/hermes-gateway` line ~297–301)

### Gateway channel config endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/gateway/channels` | GET | List all platform channel configs (status, enabled, no secrets) |
| `/api/gateway/channels/<platform>` | PUT | Update platform config (save credentials) |
| `/api/gateway/channels/<platform>/test` | POST | Test connection for a platform |
| `/api/gateway/channels/<platform>/qr/begin` | POST | Start QR onboarding, return QR image + task ID |
| `/api/gateway/channels/<platform>/qr/poll` | POST | Poll QR scan status by task ID |
| `/api/gateway/channels/<platform>/clear` | POST | Clear credentials, return to unconfigured |

### Storage

Credentials are stored in `config.yaml` under the corresponding platform key:

```yaml
feishu:
  enabled: true
  app_id: cli_xxx
  app_secret: xxx
  verification_token: xxx

dingtalk:
  enabled: false
  client_id: xxx
  client_secret: xxx

weixin:
  enabled: true
  token: xxx

wecom:
  enabled: true
  corp_id: xxx
  agent_id: xxx
  secret: xxx
  token: xxx

qqbot:
  enabled: false
  app_id: xxx
  client_secret: xxx
```

### Relevant existing code

| File | Purpose |
|---|---|
| `gateway/platforms/feishu.py` | `_begin_registration()`, `_poll_registration()`, `qr_register()` |
| `gateway/platforms/weixin.py` | `qr_login()` |
| `gateway/platforms/wecom.py` | `qr_scan_for_bot_info()` |
| `gateway/platforms/qqbot/onboard.py` | `qr_register()` |
| `gateway/config.py` | Config loading for gateway platforms |

### Implementation plan

**New files:**
- `api/gateway_mgmt.py` — backend: config CRUD, QR flow, test connection, image generation
- `static/gateway-channels.js` — frontend: panel UI, cards, QR modal, manual forms

**Minimal edits to existing files:**
- `api/routes.py` — register routes (~15 lines)
- `static/panels.js` — register new panel (~3 lines)
- `static/index.html` — include new JS + sidebar entry (~3 lines)

---

## 3. File change summary

| Change type | Files | Lines changed |
|---|---|---|
| **New** | `api/custom_provider_mgmt.py` | ~200 |
| **New** | `api/gateway_mgmt.py` | ~450 |
| **New** | `static/custom-providers.js` | ~300 |
| **New** | `static/gateway-channels.js` | ~550 |
| **Modified** | `api/routes.py` | ~30 |
| **Modified** | `static/panels.js` | ~10 |
| **Modified** | `static/index.html` | ~6 |

All modifications to existing files are kept minimal — single-line imports,
single-line hook callbacks, and routing registrations — to minimise merge
conflicts with upstream.

The existing `#gatewayStatusCard` in `static/index.html` (System tab) will be
removed since the gateway status moves to the new Gateway Channels panel.

---

## 4. System Default Language (Chinese)

### Current behaviour

The language system has a three-tier fallback chain:

```
settings.language (server) → localStorage.getItem('hermes-lang') → 'en'
```

| Layer | Location | Current value |
|---|---|---|
| Server default | `api/config.py:4139` `_SETTINGS_DEFAULTS` | `"language": "en"` |
| Autosaved setting | `settings.json` (per-user) | Set via Settings > Preferences > Language |
| LocalStorage | `hermes-lang` key | Set by `setLocale()` in `static/i18n.js` |
| Final fallback | `resolvePreferredLocale()` in `i18n.js` | `'en'` |

Browser language (`navigator.language`) is **not** consulted anywhere.

### Required changes to default to Chinese

#### Option A — Change server default (simplest)

Change the hardcoded default in `api/config.py`:

```python
# line 4139
"language": "en",   →   "language": "zh",
```

This makes Chinese the default for **all users** who have not explicitly set a
language. Existing users who already have `language: "zh"` or another value in
`settings.json` are unaffected.

#### Option B — Add browser language detection (recommended)

Add `navigator.language` detection at boot time so the UI matches the user's
browser locale automatically. In `static/i18n.js` `resolvePreferredLocale()`:

```
resolveLocale(primary) || resolveLocale(fallback) || resolveLocale(navigator.language) || 'en'
```

This way:
1. Server setting wins (if user chose a language)
2. localStorage wins (previous session)
3. Browser language wins (auto-detect)
4. English as ultimate fallback

#### Key files

| File | Purpose |
|---|---|
| `api/config.py:4139` | Server default language value |
| `static/i18n.js:12752` | `resolvePreferredLocale()` — the fallback chain |
| `static/i18n.js:12781` | `setLocale()` — switch locale and persist to localStorage |
| `static/panels.js:5259` | Language dropdown in Settings > Preferences |
| `static/panels.js:5441-5448` | Apply server-persisted language on settings load |
| `static/boot.js:1465-1496` | Boot-time locale resolution (no server yet) |
| `api/routes.py:2501` | `_resolve_login_locale_key()` — login page language matching |

---

## 5. Design decisions log

| # | Decision | Rationale |
|---|---|---|
| 1 | Custom providers in Providers panel, not independent | Fewer new UI surfaces; contextually grouped with existing provider UI |
| 2 | Gateway channels as independent panel | Five platforms + QR flows are too much for a sub-section; warrants its own space |
| 3 | Credentials hidden post-config for gateway | Security by default — gateway secrets should not be visible in the browser |
| 4 | QR code + manual form dual option for QR-capable platforms | Flexibility: user may not have phone handy, or may prefer manual input |
| 5 | DingTalk always manual (no QR) | DingTalk gateway adapter has no QR onboarding code |
| 6 | All config saved to `config.yaml` | Simpler than `.env`; consistent with existing `custom_providers` pattern |
| 7 | `config.yaml.bak` backup before each write | Rollback safety; same pattern used by existing save functions |
| 8 | Model list auto-fetched on base\_url + api\_key change | Reduces friction; user does not need to manually trigger a fetch |
| 9 | Custom provider editing via modal dialog | Clean separation from the provider card list; familiar CRUD pattern |
| 10 | Clear config button for gateway platforms | Explicit unlink action; avoids confusion about how to reset a platform |
| 11 | Gateway panel includes process start/stop/restart | Channel config is useless if gateway isn't running; one place for both |
| 12 | Gateway status moves from System tab to Gateway panel | Consolidates all gateway-related UI in one place; avoids split-brain |
