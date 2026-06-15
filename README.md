# UniuLink

A unified AI model aggregation and distribution platform with multi-provider routing, OpenAI/Claude-compatible APIs, caching, rate limiting, and visual management.

## Configuration Example

Create a `config.yaml` file in the project root and mount it to `/app/config.yaml` when running with Docker.

```yaml
app:
  # 应用名称，用于日志和管理界面展示。
  name: UniuLink
  # 运行环境。Docker 部署建议使用 production。
  env: production
  # 管理后台 API 密钥，请改成高强度随机字符串。
  admin_api_key: change-me
  # 管理后台 HMAC 签名有效期，单位为秒。
  admin_hmac_ttl_seconds: 300
  # 敏感数据加密密钥，请改成高强度随机字符串并妥善保存。
  encryption_key: change-me-32-byte-secret

database:
  # PostgreSQL 服务地址。使用 docker-compose 时保持 postgres。
  host: postgres
  # PostgreSQL 服务端口。
  port: 5432
  # PostgreSQL 数据库名。
  name: uniulink
  # PostgreSQL 用户名。
  user: uniulink
  # PostgreSQL 密码，需要和 docker-compose 中的 POSTGRES_PASSWORD 保持一致。
  password: change-me

redis:
  # Redis 连接地址。使用 docker-compose 时保持 redis 主机名。
  url: redis://redis:6379/0

gateway:
  # 单个上游渠道请求超时时间，单位为秒。
  default_channel_timeout: 30
  # 上游请求失败后的默认重试次数。
  default_max_retries: 2
  # 上游渠道健康检查间隔，单位为秒。
  health_check_interval: 30

circuit_breaker:
  # 连续失败达到该次数后触发熔断。
  failure_threshold: 5
  # 熔断后的冷却时间，单位为秒。
  cooldown_seconds: 60
  # 半开状态下允许的最大探测请求数。
  half_open_max_requests: 3

rate_limit:
  # 全局请求速率限制，单位为 RPS。
  global_rps: 1000
  # 单个 API Key 的请求速率限制，单位为 RPS。
  per_key_rps: 100
  # 单个模型的请求速率限制，单位为 RPS。
  per_model_rps: 200

cache:
  # 缓存默认过期时间，单位为秒。
  default_ttl: 3600

logging:
  # 日志级别，可选 DEBUG、INFO、WARNING、ERROR。
  level: INFO
  # 日志文件路径。留空表示输出到控制台。
  file: ''
  # 是否输出原始 JSON 日志。
  raw_json_log: false
  # 是否记录请求体。生产环境谨慎开启。
  log_body: false
  # 是否记录响应内容。生产环境谨慎开启。
  log_content: false
```
