# Onboarding Gateway IM Step — Design

在 first-run 向导末尾（password 之后，finish 之前）插入一个 gateway IM 步骤，
让用户在首次配置时就可以选择配置飞书/钉钉/微信/企微/QQ 消息平台。

## Goals

1. 在 firstrun 流程中增加可选的 gateway IM 配置步骤，降低上手后的门槛
2. 复用已有的 `gateway-channels.js` UI 组件和 `/api/gateway/` 后端接口
3. 不破坏 firstrun 现有的线性步骤导航
4. 所有 gateway 配置均为可选，用户可跳过，不影响完成 firstrun

## Non-goals

- 重写 gateway 配置 UI — 完全复用现有浮层
- 在 firstrun 内做 gateway 进程启停管理 — Settings 里做
- 支持 DingTalk QR 扫码 — 它本身没有 QR 流程

## Step order

```
['system', 'setup', 'workspace', 'password', 'gateway', 'finish']
```

| Step | 内容 | 必填 |
|------|------|------|
| system | 检测 Agent / Provider / Password 状态 | — |
| setup | 选择 Provider，API Key / Base URL | ✅ |
| workspace | 工作目录 + Model | ✅ |
| password | 设置 WebUI 密码 | 推荐 |
| **gateway** | **配置 IM 平台（飞书/钉钉/微信/企微/QQ）** | **可选** |
| finish | 摘要页 → 完成 | — |

## Interaction design

### Step page layout

```
┌──────────────────────────────────────────────────────────┐
│  步骤条: ● ● ● ● ○ ○                                    │
│                                                          │
│  添加消息平台（可选）                                     │
│  配完可以直接继续，也可以随时去 Settings → Gateway 配置    │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
│  │  飞 书    │  │  钉 钉    │  │  微 信    │  │  企业微信  │  │   QQ     │
│  │  未配置    │  │  未配置    │  │  未配置    │  │  未配置    │  │  未配置   │
│  │  [配置]   │  │  [配置]   │  │  [配置]   │  │  [配置]   │  │  [配置]  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘
│                                                          │
│                         [上一步]           [继续 →]       │
└──────────────────────────────────────────────────────────┘
```

### User flow

```
进入 gateway 步骤
       │
       ▼
  展示 5 个平台卡片
       │
       ├── 点击某平台 [配置]
       │      │
       │      ├── 有 QR 能力的平台 (飞书/微信/企微/QQ)
       │      │     ├── [扫码配置] → 弹出 QR 浮层
       │      │     │     └── 扫码确认 > 自动保存 > 关闭浮层
       │      │     │           卡片变为 "已配置 ✓"
       │      │     └── [手动输入] → 弹出凭证表单浮层
       │      │           └── 填写 > 保存 > 关闭浮层
       │      │                 卡片变为 "已配置 ✓"
       │      │
       │      └── 无 QR 能力的平台 (钉钉)
       │            └── [手动输入] → 弹出凭证表单浮层
       │                  └── 填写 > 保存 > 关闭浮层
       │                        卡片变为 "已配置 ✓"
       │
       ├── 可继续配置其他平台（多选，互不冲突）
       │
       └── 点击 [继续 →]
              │
              ▼  (跳到 finish 页)
           finish 摘要页（显示已配置的平台名）
```

### Card states

| State | Visual | Actions |
|-------|--------|---------|
| **未配置** | 平台名 + "未配置" 提示 | `[配置]` 按钮 |
| **已配置** | 平台名 + "已配置 ✓" + 绿色边框 | `[配置]` 变为 `[已配置]`（disabled） |

### 复用策略

不重新写表单组件，直接调用 `gateway-channels.js` 已有的函数：

| 函数 | 用途 |
|------|------|
| `openManualForm(platformId)` | 手动凭证填写浮层 |
| `openQRModal(platformId)` | QR 扫码浮层 |
| `refreshGatewayPanel()` | 刷新状态（用于浮层保存后更新卡片） |

### 不做的交互（避免的坑）

- ❌ 不在 gateway 步骤内分子步骤（如：选平台 → 填凭证 → 验证 → 完成）
	这个会破坏 firstrun 本身的大步骤导航（步骤条对不上）
- ❌ 不在点击卡片时跳转到外部页面
- ❌ 不在 gateway 步骤做 gateway 进程启停——用户在 Settings 里控制

## Data flow

### 保存时机

gateway 凭证的保存**在浮层内直接发生**，而非在点击 firstrun 的 [继续] 时。

```
用户点击 [保存]（浮层内）
  → fetch('/api/gateway/channels/<platform>', {method:'POST', body: credentials})
  → 后端写入 config.yaml
  → 浮层关闭
  → 卡片刷新为 "已配置 ✓"
```

`nextOnboardingStep()` 对 'gateway' key 只做一步：**不执行任何 API 调用**，直接前进到 finish。

### Finish 页展示

finish 页的摘要需要新增「消息平台」一行，读取 `ONBOARDING.status.gateway` 或直接在渲染时调用 `/api/gateway/channels` 获取已配置的平台列表。

两种方式：

| 方式 | 做法 | 优缺点 |
|------|------|--------|
| A. 在 gateway 步骤收集状态 | 浮层保存后更新 `ONBOARDING.gatewayConfigured` 数组 | 快，不需要额外 API 调用 |
| B. finish 页实时查询 | `_renderOnboardingBody('finish')` 时调 `/api/gateway/channels` | 数据一定最新，但多一次请求 |

**推荐方案 A**：gateway 浮层保存成功后，维护一个 `ONBOARDING.configuredPlatforms` 数组，
finish 页直接渲染。

## Changes required

### `static/onboarding.js`

| Change | Detail |
|--------|--------|
| `ONBOARDING.steps` | `['system','setup','workspace','password','gateway','finish']` |
| `ONBOARDING.configuredPlatforms` | 新增字段，记录已配置的平台 ID 数组 |
| `_onboardingStepMeta()` | 加 `gateway` 条目：title/desc |
| `_renderOnboardingSteps()` | 自动适配 6 步（已有逻辑通用） |
| `_renderOnboardingBody()` | 加 `key==='gateway'` 分支：渲染平台卡片网格 |
| `nextOnboardingStep()` | 加 `'gateway'` 的 case：不做任何验证，直接前进 |
| `_renderOnboardingBody('finish')` | 新增「消息平台」摘要行 |

### `static/style.css`

| Change | Detail |
|--------|--------|
| `.onboarding-gw-grid` | 平台卡片网格（5 列，响应式） |
| `.onboarding-gw-card` | 单个平台卡片 |
| `.onboarding-gw-card.configured` | 已配置状态的卡片样式 |
| `.onboarding-gw-btn` | 配置按钮样式 |

新增样式控制在 ~50 行以内。

### No changes needed

以下文件**不需要改**：

- `api/gateway_mgmt.py` — 已有完整的 CRUD / QR / test 接口
- `api/routes.py` — gateway 路由已注册
- `static/gateway-channels.js` — 直接调用其函数
- `server.py` — 不变

## Summary of changes

| File | Type | Lines |
|------|------|-------|
| `static/onboarding.js` | Modified | ~80 |
| `static/style.css` | Modified | ~50 |
| `static/gateway-channels.js` | Unchanged | 0 |
| `api/gateway_mgmt.py` | Unchanged | 0 |
| `api/routes.py` | Unchanged | 0 |

## Platform support matrix

| Platform | QR | Manual | Key fields |
|----------|----|--------|------------|
| 飞书 (Feishu) | ✅ | ✅ | `app_id`, `app_secret`, `verification_token` |
| 钉钉 (DingTalk) | ❌ | ✅ | `client_id`, `client_secret` |
| 微信 (Weixin) | ✅ | ✅ | `token` |
| 企业微信 (WeCom) | ✅ | ✅ | `bot_id`, `secret` |
| QQ | ✅ | ✅ | `app_id`, `client_secret` |

## Open questions

1. Gateway 是否需要在 firstrun 结束时自动启动？
   - 如果用户在 gateway 步骤配置了至少一个平台，是否在 finish 时自动调 `/api/gateway/start`？
   - 还是让用户去 Settings 手动启动？
   - 建议：**不自动启动**。避免用户在 firstrun 结束后 gateway 在后台跑起来但用户不知道。可以在 finish 页加一个提示："已配置 X 个消息平台，前往 Settings → Gateway 启动。"

2. 已配置平台的修改入口？
   - firstrun 内已配置的卡片只显示 "已配置 ✓"，不给修改入口（防止 firstrun 流程过于复杂）
   - 用户以后去 Settings → Gateway Channels 修改

3. DingTalk 没有 QR，卡片上只显示一个 `[配置]` 按钮还是区分开？
   - 统一用 `[配置]` 按钮，点击后根据平台是否有 QR 能力决定弹出 QR 浮层还是直接弹出表单
   - 好处：卡片 UI 干净统一，不暴露平台差异
