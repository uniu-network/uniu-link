# AGENTS.md

本文件适用于整个 UniuLink 仓库，供在项目中分析、修改和验证代码的开发代理使用。说明以当前源码为依据；修改相关实现时同步更新本文。与用户当前明确要求冲突时，优先遵循用户要求。

## 开始工作

- 先执行 `git status --short`，再阅读目标文件及相关差异。工作区可能有大量未提交修改和未跟踪的新文件，它们也是当前实现的一部分；不要覆盖、回退或顺手整理无关修改。
- 优先查阅本文的模块索引，再用 `rg` 定位调用链。核对后端处理逻辑、前端调用和测试，不要只根据 README 或依赖列表判断功能是否存在。
- 沿用当前模块边界和附近代码风格。完成任务所需的修改即可，不随意引入框架、格式化整个项目或升级依赖。
- 面向用户的说明默认使用中文，代码标识符保持英文；管理界面沿用中文文案。

## 项目定位与技术栈

UniuLink 是一个 AI 模型聚合与分发网关，包含渠道管理、公开模型映射、协议转换、路由容灾、健康检查、熔断、API Key 配额与限流、请求日志、插件和管理后台。

| 部分 | 当前实现 |
| --- | --- |
| 后端 | Python 3.11、FastAPI、Pydantic 2、Uvicorn、HTTPX |
| 持久化 | PostgreSQL；SQLAlchemy 2 异步会话、asyncpg、Alembic |
| 运行时状态 | Redis：API Key 缓存、限流、管理鉴权 nonce、健康状态缓存、熔断状态 |
| 前端 | Vue 3、TypeScript、Vite 5、Vue Router、Pinia、Axios |
| UI | Fluent Web Components 2.6.1 的 Vue 封装、Tailwind CSS 3；仪表盘实际使用 ApexCharts |
| 部署 | Docker 多阶段构建；镜像使用 Node 20、Python 3.11，Compose 配置 PostgreSQL 16 和 Redis 7 |
| 测试 | 后端标准库 `unittest`；前端 Playwright |

后端依赖以 `backend/requirements.txt` 为准。`backend/pyproject.toml` 当前只配置 Pyright，不是 Poetry/uv 项目。前端同时存在 npm 和 Yarn 锁文件；Docker 和测试脚本使用 npm，默认沿用 npm 与 `package-lock.json`，不要无故切换包管理器或重写另一份锁文件。

README 提到的响应缓存已被历史迁移移除，当前没有网关响应缓存服务。Redis 缓存和请求日志中的上游 `cache_tokens` 统计不等于响应缓存。

## 模块索引

| 路径 | 职责与阅读时机 |
| --- | --- |
| `backend/app/main.py` | FastAPI 入口、生命周期、中间件顺序、路由注册及全局错误处理 |
| `backend/app/admin.py` | 管理接口、请求 schema、渠道/模型/密钥/插件 CRUD、统计、配置、Playground |
| `backend/app/routes/` | OpenAI/Claude 兼容入口、健康端点、前端代理与 SPA 回退 |
| `backend/app/middleware/`、`backend/app/dependencies/api_key_auth.py` | trace ID、管理 HMAC、客户端 API Key 鉴权 |
| `backend/app/services/gateway_handler.py` | 网关主流程、上游调用、流式处理、错误与容灾、token 计量及日志上下文 |
| `backend/app/services/request_transformer.py` | 协议选择、请求/响应及工具调用转换、thinking 参数 |
| `backend/app/services/stream_transformer.py` | 请求级 SSE 状态、协议生命周期、内容块、工具增量、usage 与终止事件转换 |
| `backend/app/services/routing_engine.py` | 模型到渠道映射、健康与熔断过滤、排序策略、自定义 JavaScript 路由 |
| `backend/app/adapters/` | 提供商鉴权头、URL、协议适配；工厂位于 `generic_adapter.py` |
| `backend/app/services/channel_probe.py` | 探测 URL、各协议探测请求、回复文本提取，供后台手动测试及健康检查复用 |
| `backend/app/services/health_checker.py`、`circuit_breaker.py` | 定期探测与健康状态、Redis 熔断状态机 |
| `backend/app/services/cpa_manager.py`、`cpa_accounts.py`、`cpa_quota.py`、`backend/app/admin_cpa.py` | CLIProxyAPI 受管单实例：二进制安装与校验、进程启停与配置生成、按账号类型同步托管渠道、账号池管理与健康判定、配额插件安装与额度归一化 |
| `backend/app/services/api_key_service.py`、`rate_limiter.py` | 密钥验证与缓存、token 使用量、每分钟密钥限制和全局/密钥/模型 RPS |
| `backend/app/core/` | 配置、数据库、Fernet 加密、日志和响应工具 |
| `backend/app/models/`、`backend/alembic/` | ORM 表定义与历史迁移 |
| `backend/app/plugins/` | 插件协议、动态加载与内置请求日志插件 |
| `frontend/src/api/`、`frontend/src/utils/authFetch.ts` | 管理接口封装（含 `cpa.ts` 的 CLIProxyAPI 实例、账号与额度接口）、Axios HMAC 签名、流式 fetch 签名 |
| `frontend/src/views/` | 仪表盘、渠道、账号、模型、密钥、日志、插件、系统配置、演练场及登录页 |
| `frontend/src/components/ui/`、`frontend/src/composables/` | Fluent 控件封装、反馈消息、主题、表单、弹窗栈与草稿保护 |
| `frontend/src/utils/modelIdentity.ts`、`ModelIcon.vue`、`ModelLabel.vue` | 本地模型品牌图标、名称识别、手动配置优先级与未知模型回退；组件位于 `frontend/src/components/` |
| `frontend/src/router/index.ts`、`frontend/src/components/Layout.vue` | 页面路由、鉴权/离开守卫与导航 |
| `backend/tests/`、`frontend/tests/admin.spec.ts` | 后端探测单测、管理后台浏览器回归测试 |

## 环境与运行命令

下列命令按注释指定的目录执行。优先复用已有 `backend/.venv` 和已安装依赖，不要在已有虚拟环境上重新创建环境。

```bash
# 仓库根目录：需要本地数据库和 Redis 时启动依赖服务
docker compose up -d postgres redis

# backend/：仅在没有虚拟环境时，使用可用的 Python 3.11 创建
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# frontend/：安装与 Docker 构建一致的依赖
npm ci
```

`backend/environment.yml` 也提供 Conda 方案：在 `backend/` 执行 `conda env create --prefix ./.venv --file environment.yml`。venv 与 Conda 二选一，不要混用来创建同一个目录。

本地配置位于仓库根目录 `config.yaml` 或 `.env`，字段参考 README 和 `core/config.py`。至少核对数据库连接、Redis 地址、管理员密钥和加密密钥；不要将实际值复制进文档、测试或提交。宿主机运行后端时通常使用 `localhost`，Compose 内部使用服务名 `postgres` 和 `redis`。

```bash
# backend/：集成开发模式，依赖服务及配置就绪后执行
APP_ENV=development .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

- 访问 `http://127.0.0.1:8000`。`development`、`dev`、`local` 模式会由后端在空闲端口启动 Vite，并代理普通前端 HTTP 请求；存在 Yarn 时该启动器优先用 Yarn，否则用 npm。
- 需要直接使用 Vite 时，在 `frontend/` 执行 `npm run dev -- --host 127.0.0.1`，访问端口 3000；`/api/` 和 `/v1/` 会代理到 `http://localhost:8000`。若要避免后端同时管理另一份 Vite，可将后端设为 `APP_ENV=production`；这是当前模式开关的行为。
- 非开发模式由后端托管 `frontend/dist`，需要先在 `frontend/` 执行 `npm run build`。
- 启动后端会执行 Alembic 迁移到 head、连接 Redis、加载插件并启动渠道探测。当前数据库若包含真实渠道，探测可能发送上游请求；离线验证优先使用现有 mock 测试。
- `/health` 是存活检查；`/ready` 当前实际只检查 Redis，返回值中的数据库状态不能视为已验证数据库连接。

## 接口和鉴权契约

| 接口 | 用途 |
| --- | --- |
| `GET /v1/models` | OpenAI 格式模型列表 |
| `POST /v1/chat/completions` | OpenAI Chat Completions |
| `POST /v1/responses` | OpenAI Responses |
| `GET /v1/messages/models` | Claude 格式模型列表 |
| `POST /v1/messages` | Claude Messages |
| `/api/admin/*` | 管理后台，包括 `/auth/verify` 和 `/playground` |

- `/v1/*` 使用客户端 API Key，主要接受 `Authorization: Bearer ...` 或 `x-api-key`。`require_api_key` 检查启用状态、有效期、token 配额及密钥每分钟频率；生成请求的模型权限检查位于网关处理器。不要将后台管理员密钥和客户端密钥混用。
- `/api/admin/*` 使用 `X-Admin-Timestamp`、`X-Admin-Nonce`、`X-Admin-Signature`。签名原文为 `METHOD\nPATH\nTIMESTAMP\nNONCE\nSHA256(BODY)`，密钥是管理员密钥，算法为 HMAC-SHA256，时间戳单位为秒。后端签名路径不含 query，nonce 使用 Redis 记录。
- 修改签名行为时同时检查 `middleware/auth.py`、`src/api/client.ts`、`src/utils/authFetch.ts` 和登录测试。query 应通过 Axios 的 `params` 传入；序列化后的请求体必须与签名计算一致。
- 管理成功响应使用 `success_response()`：`{ is_success_response: true, message, data: { detail_msg, detail_result } }`。Axios 拦截器解包到 `detail_result`；列表结果内部还可能有 `data`、`total`、分页字段，不要多解包或少解包一层。
- `/v1/*` 保留对应协议的响应及错误形状，不能套管理后台成功包装；使用 `core/response.py` 中的协议错误工具。
- Playground 使用管理鉴权，通过 `_api_type` 选择协议并复用网关；它没有普通客户端密钥 ID，不应记到某个客户端密钥的 token 配额上。
- 保持 `x-request-id`、`x-trace-id` 与日志 `trace_id` 的贯通。

## 网关修改原则

典型请求流程：客户端鉴权 → 请求和模型权限检查 → RPS 限流 → thinking 默认值 → `pre_route` → 路由及 `on_channel_select` → `pre_request` → 上游模型名映射/协议转换/适配器 → 上游 HTTP → 返回协议转换 → token 计量与 `post_send` 日志。流式与非流式有独立执行分支，修改一支后必须检查另一支。

- 区分客户端请求协议、渠道 `api_type` 和 `provider`。协议值主要是 `openai`、`responses`、`claude`，渠道还支持 `auto`；`auto` 的选择规则在 `resolve_channel_api_type()`，不是简单透传客户端协议。
- 公共请求/响应转换放在 `request_transformer.py`，SSE 状态与转换放在 `stream_transformer.py`，提供商差异放在适配器。每次上游流式调用必须使用独立 `StreamState`。`google` 和 `custom` 当前使用 `GenericAdapter`，不要据此宣称支持原生 Gemini 协议。
- URL 拼接复用 `build_upstream_url()` / `build_models_url()`，保留已有版本路径、完整 endpoint 和 query，避免重复 `/v1`。Azure deployment URL 有特殊处理。
- 自定义请求头通过 `merge_custom_headers()` 合并；保留对 `Authorization`、`api-key`、`x-api-key` 的大小写无关保护。
- 路由目标有 `reference` 和 `inline` 两种；`upstream_model_id` 是调用上游的名字，不能误用公开模型名。内联目标没有 `channel_id`，熔断键使用 `ChannelInfo.circuit_key`，回退到 `ref_id`。
- 路由按 `priority` 升序读取，支持 `default`、`random`、`weighted`、`custom_js`。`failover_enabled=false` 时只保留第一个候选。`custom_js` 实际调用 Node 子进程，不是隔离沙箱；Python 插件同样执行服务端代码，只适用于可信管理配置。
- `max_retries` 虽然存在于配置和数据结构，当前网关主要实现逐渠道容灾，没有按该字段重复调用同一渠道的循环。不要把字段存在当作重试功能已实现。
- 上游 HTTP 400 当前直接结束；其他错误可能触发下一渠道。流式响应一旦已经向客户端发出转换后的数据，就不能回退重放到另一渠道。
- 流式换号依赖 `stream_gateway_request()` 的首块缓冲（`_STREAM_HOLDBACK_SECONDS`、`_STREAM_HOLDBACK_MAX_BYTES`）：开头的生命周期帧先积压，只有出现可见输出、终止事件、缓冲到量或超出时限才释放。因此判空失败时 `data_sent` 仍为 False，可以正常换号；时限到期即放弃换号机会，避免慢模型的首字节被无限推迟。改动该窗口时注意它必须显著小于前置代理/CDN 的空闲超时，否则积压会被误判成断流。
- 只有 `visible_output_seen` 判定为真才算有输出：正文、工具调用，以及 Claude 目标的 thinking 块计入；Chat 与 Responses 目标的 reasoning 不计入，因为它们的可见文本字段仍为空，这正是客户端报「no content」的原因。跨协议由 `_append()` / `_block()` 置位，同协议透传由 `_observe_frame_content()` 直接检查原始事件——该路径不经过各协议 reader，结束原因也在此记录，否则被截断的空流会被误判为静默拒绝。responses 透传若上游不发增量、仅在终止事件内嵌 `response.output`，其中的 message/function_call item 同样计入（reasoning item 仍不计入）。
- SSE 解析必须处理分块边界、多行 data 和完整事件，保持各协议终止标记、错误事件、Claude 内容块顺序及 thinking 状态。只有协议终止事件才表示完成；空流、提前 EOF、只有 usage（`choices: []`，网关自己通过 `stream_options.include_usage` 请求）或只有 reasoning 的终止事件，以及 HTTP 200 中的错误事件，均按失败处理，不能补造成功结束事件。`length`、`max_tokens`、`max_output_tokens`、`content_filter`、`refusal`、`tool_calls`、`function_call`、`tool_use` 与 `response.incomplete` 属于合法空终止，必须放行。不能仅验证最终拼接文本。
- 跨协议保留通用 function 工具定义、工具历史、调用 ID、参数增量和结果。提供商原生工具及多 choice 请求不能跨协议转换，返回 400 协议错误（流式在 SSE 中报告）；同协议继续透传。Chat/Responses 的 reasoning 转 Claude 时，流式使用 `thinking` 块和 `thinking_delta`，非流式使用 `thinking` 内容块，不得降级为正文。缺少上游签名时生成兼容占位签名，流式在 thinking 块结束前补一次 `signature_delta`；已有签名原样保留。占位签名不代表 Claude 官方校验通过。并行工具转 Claude 时缓存工具参数及后续块，按顺序结束内容块。
- 修改 usage 时同时检查非流式提取、流式累积、密钥使用量、请求日志和仪表盘，区分 prompt/completion/total/cache tokens。
- 流式结束、异常或客户端断开时，在屏蔽取消的 finally 中累计各次尝试已收到的 usage、扣量并执行一次 `post_send`；未收到的 usage 不能推算成已知用量。
- 健康检查支持 `model_list`、`prompt` 和 `account_pool`；模型列表返回非 2xx 时会尝试 prompt 回退。探测模型必须来自已配置的上游模型列表。手动测试和定时检测共用探测工具与状态写入方法。
- `account_pool` 仅用于托管 CLIProxyAPI 实例自动生成的渠道：判定标准是 CPA 进程存活（`/healthz` 200）且该渠道对应账号类型的账号池中至少有一个可调度账号。托管渠道按账号类型拆分，因此**只统计 `cpa_provider` 对应类型的账号**（`cpa_provider` 为空时才统计全池），避免其它类型的可用账号掩盖本类型的不可用。账号可用性以 CPA 的 `unavailable` 为准，`disabled`、`status == "disabled"`、未到期的 `next_retry_after` 以及凭据级（`auth`/`credential`）冷却也算不可用；模型级冷却不会让整个账号失效，因为 CPA 仍会用该账号服务其它模型。不要改为探测模型列表，那会与账号池实际可用性脱节。
- 健康状态写入 PostgreSQL 并缓存在 Redis；熔断状态主要保存在 Redis。不要仅修改 ORM 上的 `circuit_state` 就认为运行时熔断已变化。
- 熔断候选过滤只读；仅在实际调用上游时通过 `request_permit()` 原子获取半开探测名额。探测租约定时续期，取消时释放，进程异常退出后自动过期。结算携带 permit 的代次，旧请求和过期探测不得关闭新一轮熔断；冷却后探测失败重新熔断，成功关闭熔断。

## 数据与迁移

| ORM 模型 / 表 | 含义 |
| --- | --- |
| `Channel` / `channels` | 可复用上游渠道、加密后的凭据、协议、探测配置；`auto_managed` 标记由托管实例生成的渠道，`cpa_instance_id` 与 `cpa_provider` 记录其归属实例与账号类型 |
| `CpaInstance` / `cpa_instances` | CLIProxyAPI 受管单实例：监听地址/端口、二进制与安装目录、加密后的管理密钥与访问密钥、自动启动开关及进程快照；由后端自动创建，管理接口不提供增删 |
| `ModelConfig` / `model_configs` | 对外模型名、路由策略、容灾与 thinking 默认值 |
| `ModelChannelRef` / `model_channel_refs` | 模型到引用/内联渠道的映射、权重、优先级、上游模型 ID |
| `ApiKey` / `api_keys` | 客户端密钥哈希、前缀、配额、权限、有效期和使用量 |
| `RequestLog` / `request_logs` | trace、调用密钥归属、渠道、状态、延迟、usage、可选正文 |
| `Plugin` / `plugins` | 插件模块路径、启用状态、优先级与配置 |

- 后端沿用四空格缩进、类型注解、Pydantic 请求模型及 SQLAlchemy `Mapped` 映射；I/O 路径保持异步，不在请求处理中引入阻塞调用。
- 使用 SQLAlchemy 异步会话。`get_db()` 包含提交/回滚逻辑；后台任务、自建 `AsyncSessionLocal()` 的写操作要明确提交，并避免把已关闭会话传给后台任务。
- 渠道 API Key 和内联凭据通过 `key_encryption` 加解密；客户端密钥只保存哈希和前缀，创建时返回明文。保持这些边界，更新密钥属性后同步失效 Redis 缓存。
- 对外渠道字段 `default_weight` 对应 ORM `weight`；模型渠道引用还有自己的 `weight`。变更字段时同步检查 `admin.py` schema、ORM、前端表单/API 和 fixture。
- schema 变更需要新增迁移，并检查 `alembic/env.py` 是否导入新模型。保留迁移链，不回写已发布迁移。

- 空库初始化与已有版本升级统一在 `backend/` 执行 `.venv/bin/alembic upgrade head`；应用启动也通过 `init_db()` 执行同一迁移链并记录版本，不使用 `create_all()` 建表。
- `20260530_0001` 是原始表结构的固定基线，后续连接原有增量迁移。迁移文件不能依赖当前 ORM 定义来创建历史 schema。
- CLIProxyAPI 相关的增量迁移：`20261012_0001` 建 `cpa_instances` 表并给 `channels` 加 `cpa_instance_id`、`auto_managed`，`20261013_0001` 再加 `cpa_provider`（当前 head）。
- 自动生成迁移使用 `.venv/bin/alembic revision --autogenerate -m "描述"`，生成后审阅 upgrade/downgrade，并验证迁移后的 schema 与 ORM 一致。

## 前端实现约定

- 页面使用 Vue SFC 的 `<script setup lang="ts">`、Composition API 和 `@/` 别名；沿用现有两空格缩进、单引号及通常省略分号的风格，避免无关格式化。
- 普通管理请求放在 `src/api/` 并复用 `client.ts`；Playground 的 SSE 使用 `authFetch()` 与流读取。不要在页面另外实现签名或混用响应包装。
- 优先复用 `UiButton`、`UiInput`、`UiSelect`、`UiCheckbox`、`UiModal`、`UiDataTable` 等封装，以及 `PageHeader`、`ListState`。这些封装承担属性同步、类型转换、禁用状态和无障碍语义。
- Fluent 在 `src/fluent.ts` 注册，Vite 配置将 `fluent-*` 识别为自定义元素。对 Web Components 的 `value`、`checked` 等使用现有 `.prop` 绑定，保留数字/布尔值的请求类型。
- `UiSelect` 包含空选项及异步选项同步处理，`UiModal` 和 `useDialogStack` 处理嵌套弹窗、Escape、焦点归还和滚动锁。修改这些基础组件时须运行相关浏览器测试，不能以简化代码为由删除兼容逻辑。
- 表单复用 `useUnsavedForm`，其他草稿用 `useDraftGuard`；离开页面、关闭弹窗、退出登录和提交中状态都要考虑草稿保护。`App.vue` 按 `route.path` 挂载页面，只有 query 改变不应清空草稿。
- 使用 `useToast` / `useConfirm` / `notify` 提供统一反馈。全局 viewport 已在 `App.vue` 挂载，不在页面重复创建；保持消息跨路由展示、独立计时及暂停行为。
- 主题通过 `useTheme.ts` 的 Fluent design tokens 与 `styles.css` 的 CSS 变量协同实现。保留跟随系统/浅色/深色、存储不可用回退和 `prefers-reduced-motion` 支持；不要给单个控件随意覆盖整套官方视觉样式。
- 全局圆角使用 Fluent 的 `controlCornerRadius` / `layerCornerRadius`；徽章使用官方 `neutral` 外观。页面、卡片、表格、菜单和弹窗使用短时淡入/位移，图表动画也遵守减少动态效果设置。移动侧边栏保留 64px 导航栏与 272px 展开宽度。
- 模型图标由 `@lobehub/icons-static-svg` 的静态子集打包，运行时不请求图标 CDN。`ModelConfig.icon` 经迁移 `20261005_0001` 持久化；管理接口创建/更新接受白名单图标 ID，默认 `auto`，`generic` 强制通用图标，局部更新省略 `icon` 时保留原值。新增图标同步后端 `ModelIconName`、前端映射与测试。
- 手动图标优先于名称识别；自动模式仅在所有上游模型都能识别且品牌一致时推断自定义别名，混合/未知目标使用通用图标。图标不代表协议支持或真实提供商验证，也不参与路由。模型卡片、演练场、密钥模型选择与日志共用此展示规则；日志额外读取模型目录失败时仍可浏览。
- 渠道与模型支持本地搜索/筛选。渠道与日志表通过复合单元格减少列数；`UiDataTable` 的列 `width` 为最小宽度，窄屏保留横向滚动及键盘访问。
- 「账号管理」页面（`Accounts.vue`）同时承担 CLIProxyAPI 的实例运维与账号池管理：实例操作（安装/启动/重启）、账号 OAuth 登录、凭据导入导出、批量启停与删除，以及「额度」列。额度按 `auth_index` 与账号行对应，重置时间按 `MM-DD HH:mm` 本地化显示；插件未就绪时展示提示与「安装配额插件」入口，而不是报错。
- 新增页面同时检查 router 的 `requiresAuth` / `title`、Layout 导航和浏览器 fixture；保持移动端布局、可访问名称和键盘操作。

## 配置、部署和插件的现有边界

- 配置优先级为：进程环境变量 → 根目录 `.env` → 根目录 `config.yaml` → 代码默认值。来源以 `core/config.py` 的 `CONFIG_META`、`YAML_SECTION_MAP`、`YAML_KEY_ALIASES` 为准；配置路径按源码位置推导，不依赖当前工作目录。
- 新配置需同步 Settings、元数据、YAML 映射/别名及相关说明。只有 `hot_reloadable` 字段可通过管理接口更新；数据库连接、管理员密钥、加密密钥等需要重启。
- `ConfigManager.update()` 原地修改设置，但 `reload()` 会替换 Settings 对象；其他模块已导入的 `settings` 不会自动重新绑定。不要假定 `/config/reload` 已让所有模块刷新。
- YAML 持久化写入规范字段名，而读取时短别名会覆盖同名规范字段；已有短别名可能使重启后的值与刚更新的值不同。写入失败目前被忽略，界面显示成功不代表落盘成功，尤其是只读挂载。
- Docker 中后端位于 `/app/app`，上述路径计算使配置位于 `/config.yaml`、静态文件位于 `/frontend/dist`；Compose 的配置挂载是 `./config.yaml:/config.yaml:ro`。README 所写 `/app/config.yaml` 与实际路径不一致，排查部署时以代码及 Compose 为准。
- Docker 保留 Node 运行时供 `custom_js` 路由使用，并以单 Uvicorn worker 运行；每个应用进程都会启动健康检查循环，调整 worker 数量时要考虑重复后台任务。
- Docker 构建通过 HTTPS 使用 Debian 官方软件源和官方 PyPI，避免第三方镜像源拒绝下载导致构建失败。
- 插件继承 `PluginHook`，内置 `builtin_*.py` 自动发现，数据库插件按优先级降序导入。hook 包括 `pre_route`、`on_channel_select`、`pre_request`、`post_response`、`on_error`、`post_send`。
- 插件数据库 CRUD 不会自动刷新内存中的插件列表，当前需要重启才能重新加载。`hook_type` 被保存，但加载/分发并未按该字段过滤；非流式的 `post_response`、`on_error` 行为也不能直接套用到流式分支。
- 请求日志通过内置 `LoggingPlugin.post_send()` 落库：非流式使用后台任务，流式在生成器 finally 中执行，避免断开连接后遗漏日志。`log_body`、`log_content` 控制网关日志正文；`core/http_debug.py` 另外在 DEBUG 级别记录上游正文，不受这两个开关控制。排查时不要泄露凭据或真实对话内容。
- `config.yaml`、`.env`、虚拟环境、`node_modules`、`dist`、浏览器测试产物和运行日志属于本地配置或生成文件，不纳入功能提交。

## CLIProxyAPI 托管

UniuLink 直接托管 CLIProxyAPI（CPA）的安装与进程，管理员只需在「账号管理」页面安装、启动实例并登录账号，不需要手动填写上游 API URL。

- 相关配置为 `cpa_manage_enabled`（默认 `False`）、`cpa_install_dir`、`cpa_release_repo`、`cpa_download_base_url`、`cpa_start_timeout`、`cpa_quota_plugin_enabled`（默认 `True`），YAML 节名为 `cpa`，短别名去掉 `cpa_` 前缀（如 `cpa.quota_plugin_enabled`）。这些字段均为热更新。`cpa_install_dir` 留空即用默认值 `backend/.uniulink`，无需手工配置。
- 托管实例是**单例**：`get_or_create_instance()` 在首次访问时自动创建，管理接口只提供 install / start / stop / restart / sync-channels，没有增删实例的入口。不要照搬多实例 CRUD 的交互。
- 只有显式开启 `cpa_manage_enabled` 才允许自动下载并执行官方 Release 二进制，且仅 `/instance/install` 校验该开关；安装前校验 `checksums.txt` 中的 SHA256。`verify_local_binary()` 与“指定本地 `binary_path`”目前没有接口入口，属于遗留函数，不要据此向用户承诺该用法。
- 实例在 `install_dir` 下拥有独立的配置、`auths/` 与 `logs/`，监听 `127.0.0.1` 并在 `remote-management.allow-remote: false` 下运行。配置文件按 0600 原子写入，含自动生成的访问密钥与管理密钥（Fernet 加密存于 `cpa_instances`）。CPA 以 `cwd=install_dir` 启动，因此配置里的 `auth-dir` 等路径必须写绝对值。
- **渠道按账号类型拆分**，名称为 `CliProxyAPI-<账号类型>`（类型取界面标签），`auto_managed = True`、`provider = "cliproxyapi"`、`health_check_mode = "account_pool"`，并用 `cpa_provider` 记录该类型。每个账号类型一个渠道，不再是「一个实例一个渠道」。没有账号的类型不建渠道，账号被清空的类型会移除其渠道，历史遗留的实例级渠道（`cpa_provider` 为空）一并清理。管理接口拒绝手动创建、编辑和删除这类渠道。
- 「账号管理」页面通过 CPA 管理接口（`/v0/management/*`）管理账号池：启停账号、刷新 Token、重置冷却、导入/导出凭据，以及 OAuth 向导登录。进程状态、账号池健康与渠道健康都由后端实时读取，不写入实例表以外的缓存。
- 「账号管理」页面的**「额度」列**展示每个账号的套餐、各时间窗剩余百分比与重置时间，数据来自配额插件（见下节）。插件未就绪时该列显示为空，页面给出「安装配额插件」入口。
- 应用启动时 `reconcile_instances()` 接管仍存活的实例进程、按需拉起 `auto_start` 实例并同步托管渠道；关闭时 `shutdown_reapers()` 结束回收与后台任务。`cpa_instances` 中的 `pid`、`status` 只是快照，判定运行状态以实际进程和 `/healthz` 为准。

## CLIProxyAPI 配额插件

额度能力由 CPA 原生插件提供，插件产物与配置由 UniuLink 自动管理，管理员无需手工安装。

- 默认插件是 `cpa-quota-api-extension`（常量 `QUOTA_PLUGIN_ID`），覆盖 Codex / Claude / Antigravity / Gemini CLI 等账号类型，提供套餐、剩余百分比与重置时间。`cpa_quota_plugin_enabled`（默认 `True`）控制是否启用整套机制。
- `build_config()` 会写入 `plugins.enabled: true` 与绝对路径的 `plugins.dir`（位于实例安装目录下的 `plugins/`）。`configs.<id>.enabled` **只在该插件产物已落盘时**才写入：CPA 会把缺失值归一成 `false`（不写会导致下次启动后插件被禁用），但空环境里预写又会让 `GET /plugins` 把不存在的插件列为已安装。
- **判断是否已安装必须以磁盘产物为准**（`quota_plugin_installed()` 查找 `plugins/` 下的 `*.so`/`*.dylib`/`*.dll`），不能用 `GET /plugins` 的条目存在性。曾因用后者做判定，空环境被误判为「已安装」，于是既不安装又空等加载超时。
- 安装走 CPA 插件商店：`POST /v0/management/plugin-store/<id>/install`，由 CPA 自行下载、校验 checksums 并解包，`restart_required: false` 即热加载。安装是**异步**的：返回后 CPA 才重载配置并注册插件，注册完成前访问插件路由会得到 **404**，因此要轮询等待（`_wait_until_loaded`）。插件日志表现为 `pluginhost: plugin loaded` / `plugin registered`。
- **安装与等待必须放在后台任务**（`schedule_quota_plugin_setup()`），实例启动接口与 `reconcile_instances()` 都不能同步等待：历史上曾因此让应用启动和 `/instance/start` 各阻塞 30 秒以上。
- 插件没有实现 CPA 原生的 `QuotaProvider`，所以 `/v0/management/quota/fetch` 固定返回 501，不能用它取额度；额度一律走插件自己的只读路由 `/v0/management/plugins/<id>/v1/quotas`（支持 `provider`/`status`/`limit`/`cursor` 与 `refresh=true`）。
- 各家上游字段不一致（`remaining_percent` / `remainingPercent` / `remainingFraction` / `resets_at` / `resetTime` 混用），`cpa_quota.normalize_account()` 采用防御式递归提取：找出所有形如额度窗口的对象，缺一侧百分比按 100 互补，`remainingFraction` 按 0~1 比例处理，并把**共享同一配额的多个模型合并成一行**（如 Antigravity 把同一配额重复写在 27 个模型上）。
- 额度快照接口为 `GET /accounts/quota`、`POST /accounts/quota/refresh`、`POST /accounts/quota/install`（幂等）。实例未运行时返回 `available: false` 与原因，而不是报错。
- 该插件是**第三方原生动态库**，在 CPA 进程内以完全权限运行并可读取全部账号凭据；与 `custom_js` 路由同属「只适用于可信管理配置」的范畴，审查时不要默认它可信。

## 验证方式

```bash
# backend/：现有后端单元测试，无需启动真实上游或数据库服务
.venv/bin/python -m unittest discover -s tests -v

# backend/：在专用 PostgreSQL 测试库中运行迁移集成测试
TEST_POSTGRES_URL='postgresql+psycopg2://USER:PASSWORD@127.0.0.1:PORT/TEST_DB' .venv/bin/python -m unittest discover -s tests -p test_migrations.py -v

# frontend/：仅类型检查，或执行含类型检查的完整生产构建
npm run typecheck
npm run build

# frontend/：浏览器回归；首次运行且缺少浏览器时安装 Chromium
npx playwright install chromium
npm run test:e2e

# frontend/：按测试名筛选，或仅列出用例（列出不代表通过）
npm run test:e2e -- --grep "playground"
npm run test:e2e -- --list
```

- 后端使用 `unittest.TestCase` / `IsolatedAsyncioTestCase`、`unittest.mock`。测试覆盖探测文本提取、URL 去重、协议 token 字段、健康探测回退、流式协议转换和迁移；仓库保留的测试尚未覆盖完整网关或 Redis 状态机。必须查看 skip 结果。
- `test_cpa_accounts.py` 覆盖 CPA 账号的纯函数逻辑：时间戳解析、账号可用性（禁用/冷却/`next_retry_after`）、状态归一、池汇总、凭据序列化、`checksums.txt` 解析、平台产物名与按账号类型的渠道命名，不发真实上游请求。额度归一化（`cpa_quota.normalize_account`）目前**没有**单测覆盖，改动它时需自行补充验证。
- `test_stream_transformer.py` 使用 HTTP mock 与已安装的 OpenAI/Anthropic SDK 验证六种跨协议流转换、工具历史与非流式响应转换、usage、结束原因、内容块顺序、错误事件、思考与正文分离、兼容签名补齐和已有 Claude 签名透传，不访问真实上游。网关取消、容灾及熔断改动还需使用 ASGI mock 和隔离 Redis 验证。
- `test_migrations.py` 默认使用内存 SQLite 验证空库、历史版本数据保留、重复升级、回滚及 ORM 结构一致性。设置 `TEST_POSTGRES_URL` 后还会在随机隔离 schema 中执行 PostgreSQL 测试和真实异步启动测试；不设置时这部分跳过。
- Pyright 配置在 `backend/pyproject.toml`；环境中已安装 Pyright 时可从 `backend/` 执行 `pyright`。它没有列入后端依赖，不要声称默认安装即可运行。
- Playwright 自动在 `127.0.0.1:3000` 启动或复用 Vite，使用单 worker 和 `Asia/Shanghai` 时区。测试通过 `page.route()` mock 管理 API，不要求启动真实后端；因此通过不代表后端 HMAC、数据库或上游集成已验证。
- 浏览器测试覆盖登录签名、九个后台页面、主题、移动端、草稿保护、弹窗焦点、表单 payload、消息、日志过滤和三种 Playground 流格式。新增管理字段时同步 fixture 与 payload 断言。
- 模型图标回归覆盖手动保存/重载/恢复自动、跨页面一致性、未知与混合路由回退、搜索筛选、暗色及减少动态效果；`test_model_icons.py` 验证管理 schema、局部更新和接口读写，迁移测试验证旧数据默认值与手动图标持久化。
- 当前没有统一 lint 脚本或 CI 工作流。不要编造 `npm test`、`npm run lint`、pytest、Ruff 等项目命令；需要新增工具时明确说明并纳入任务范围。
- 根据修改选择验证：纯文档核对路径和命令；前端运行构建并按影响运行 E2E；网关/鉴权/路由改动补充相关行为回归；schema 改动在隔离开发库验证迁移。使用 mock 避免不必要的真实上游调用。

## 完成工作时

- 检查本次文件差异和空白错误，确认没有覆盖用户改动，也没有混入密钥、日志或生成产物。
- 报告具体行为变化、执行过的验证及结果；区分通过、失败、跳过与未执行。构建告警与测试失败分别说明。
- 如果发现现有缺陷超出本次范围，记录相关文件、影响和验证边界，不顺手扩展成无关重构。
- 变更启动方式、接口契约、配置或关键模块边界时，同步维护本文及相关 README 内容。
