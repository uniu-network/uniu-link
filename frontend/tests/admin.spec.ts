import { test, expect, type Page, type Route } from '@playwright/test'
import { createHmac, createHash } from 'node:crypto'

const channel = {
  id: 'ch-1',
  name: '主渠道',
  provider: 'openai',
  api_type: 'openai',
  base_url: 'https://upstream.example/v1',
  api_key: '',
  timeout: 30,
  max_retries: 2,
  default_weight: 1,
  custom_headers: {},
  upstream_models: ['model-a'],
  health_check_mode: 'model_list',
  health_status: 'healthy',
  circuit_state: 'closed',
}
const model = {
  id: 'm-1',
  name: 'model-a',
  display_name: '测试模型',
  routing_strategy: 'default',
  channel_refs: [],
  supports_thinking: true,
  default_thinking_effort: 'none',
  claude_thinking_mode: 'adaptive',
  failover_enabled: true,
  is_listed: true,
  custom_js: '',
}
const plugin = {
  id: 'p-1',
  name: '日志插件',
  hook_type: 'pre_route',
  module_path: 'app.plugins.Logging',
  priority: 0,
  config: {},
  enabled: true,
}
const key = {
  id: 'k-1',
  name: '演练密钥',
  key_prefix: 'sk-demo',
  is_active: true,
  used_tokens: 10,
  max_tokens: 100,
  allowed_models: [],
  rate_limit: 0,
}
const log = {
  id: 'l-1',
  trace_id: 'trace-123456789',
  api_type: 'openai',
  model: 'model-a',
  selected_channel_name: '主渠道',
  status_code: 200,
  latency_ms: 150,
  prompt_tokens: 10,
  completion_tokens: 20,
  total_tokens: 30,
  created_at: '2026-10-03T00:00:00Z',
  request_body: '{"model":"model-a"}',
  output_content: '测试输出',
}
async function fixtures(page: Page, authenticated = true) {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'warning' && message.text().includes('[Vue warn]'))
      errors.push(message.text())
  })
  if (authenticated)
    await page.addInitScript(() => localStorage.setItem('admin_key', 'fixture-key'))
  await page.route('**/api/admin/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let data: unknown = { data: [] }
    if (path === '/api/admin/channels') data = { data: [channel] }
    if (path === '/api/admin/models') data = { data: [model] }
    if (path === '/api/admin/plugins') data = { data: [plugin] }
    if (path === '/api/admin/api-keys') data = { data: [key] }
    if (path === '/api/admin/logs') data = { data: [log], total: 41 }
    if (path === '/api/admin/config')
      data = {
        default_channel_timeout: {
          value: 30,
          default: 30,
          type: 'int',
          description: '上游超时',
          hot_reloadable: true,
        },
        log_body: {
          value: false,
          default: false,
          type: 'bool',
          description: '记录请求体',
          hot_reloadable: true,
        },
      }
    if (path === '/api/admin/stats')
      data = {
        total_requests: 12,
        error_rate: 0,
        channel_health: [channel],
        token_stats: { total_tokens_last_hour: 30 },
        api_key_stats: [
          {
            from_apikey: 'k-1',
            from_apikey_name: '演练密钥',
            request_count: 12,
            error_count: 0,
            total_tokens: 30,
          },
        ],
        stats_charts: {
          hourly: [
            {
              time: '2026-10-03T00:00:00Z',
              total_tokens: 30,
              prompt_tokens: 10,
              completion_tokens: 20,
              request_count: 12,
              error_count: 0,
              healthy_channels: 1,
            },
          ],
          daily: [],
        },
      }
    if (path.endsWith('/sync-models')) data = { total: 1 }
    if (path.endsWith('/test')) data = { success: true, reply: 'hello', latency_ms: 10 }
    await route.fulfill({ json: data })
  })
  return errors
}
function button(page: Page, name: string) {
  return page.getByRole('button', { name, exact: true })
}
async function select(page: Page, label: string, option: string) {
  const control = page.getByRole('combobox', { name: label, exact: true })
  await control.click()
  await page.getByRole('option', { name: option, exact: true }).click()
}
async function routeTo(page: Page, path: string) {
  await page.evaluate(async (path) => {
    await (document.getElementById('app') as any).__vue_app__.config.globalProperties.$router.push(
      path
    )
  }, path)
}
async function more(page: Page, index = 0) {
  await button(page, '更多操作').nth(index).click()
}

test('all eight views render official controls with no runtime errors', async ({ page }) => {
  const errors = await fixtures(page)
  const routes = [
    ['/', '仪表盘'],
    ['/channels', '渠道管理'],
    ['/models', '模型管理'],
    ['/logs', '请求日志'],
    ['/api-keys', 'API 密钥'],
    ['/plugins', '插件管理'],
    ['/config', '系统配置'],
    ['/playground', '演练场'],
  ]
  for (const [path, name] of routes) {
    await page.goto(path)
    await expect(page.getByRole('heading', { name, exact: true, level: 1 })).toBeVisible()
    await expect(page.locator('.loading-state')).toHaveCount(0)
    await expect(page.locator('.navigation-item[aria-current="page"]')).toHaveText(name)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  }
  await expect(page.getByRole('combobox', { name: '模型', exact: true })).toHaveText(/测试模型/)
  expect(errors).toEqual([])
})

test('login preserves HMAC signature and native form submission', async ({ page }) => {
  const errors = await fixtures(page, false)
  await page.goto('/login')
  await page.getByRole('textbox', { name: 'Admin API Key' }).fill('fixture-key')
  const requestPromise = page.waitForRequest('**/api/admin/auth/verify')
  await page.getByRole('textbox', { name: 'Admin API Key' }).press('Enter')
  const request = await requestPromise
  const headers = request.headers()
  const bodyHash = createHash('sha256').update('').digest('hex')
  const signature = createHmac('sha256', 'fixture-key')
    .update(
      `POST\n/api/admin/auth/verify\n${headers['x-admin-timestamp']}\n${headers['x-admin-nonce']}\n${bodyHash}`
    )
    .digest('hex')
  expect(headers['x-admin-signature']).toBe(signature)
  await expect(page.getByRole('heading', { name: '仪表盘', exact: true, level: 1 })).toBeVisible()
  expect(errors).toEqual([])
})

test('system/light/dark cycle, persistence and system changes', async ({ page }) => {
  const errors = await fixtures(page)
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.goto('/channels')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.getByRole('button', { name: /当前主题：跟随系统/ }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  await page.emulateMedia({ colorScheme: 'dark' })
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  await page.getByRole('button', { name: /当前主题：浅色模式/ }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  const cardColor = await page
    .locator('fluent-card')
    .first()
    .evaluate((e) => getComputedStyle(e).backgroundColor)
  expect(cardColor).not.toBe('rgb(255, 255, 255)')
  await page.reload()
  await expect(page.getByRole('button', { name: /当前主题：深色模式/ })).toBeVisible()
  await page.getByRole('button', { name: /当前主题：深色模式/ }).click()
  await page.emulateMedia({ colorScheme: 'light' })
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  expect(errors).toEqual([])
})

test('theme and login still work when localStorage is unavailable', async ({ page }) => {
  const errors = await fixtures(page, false)
  await page.addInitScript(() => {
    Storage.prototype.getItem = () => {
      throw new Error('storage blocked')
    }
    Storage.prototype.setItem = () => {
      throw new Error('storage blocked')
    }
  })
  await page.goto('/login')
  await page.getByRole('button', { name: /当前主题：跟随系统/ }).click()
  await page.getByRole('button', { name: /当前主题：浅色模式/ }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.getByRole('textbox', { name: 'Admin API Key' }).fill('fixture-key')
  await button(page, '登录').click()
  await expect(page.getByRole('heading', { name: '仪表盘', exact: true })).toBeVisible()
  expect(errors).toEqual([])
})

test('mobile rail, overlay, Escape and dialogs fit without horizontal overflow', async ({
  page,
}) => {
  const errors = await fixtures(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/channels')
  await expect(page.locator('.sidebar')).toHaveCSS('width', '64px')
  const before = await page.locator('.main-content').boundingBox()
  await button(page, '展开侧边栏').click()
  await expect(page.locator('.sidebar')).toHaveCSS('width', '272px')
  await expect(page.locator('.sidebar-scrim')).toBeVisible()
  expect((await page.locator('.main-content').boundingBox())?.x).toBe(before?.x)
  await page.keyboard.press('Escape')
  await expect(page.locator('.sidebar-scrim')).toHaveCount(0)
  await button(page, '展开侧边栏').click()
  await page.locator('.sidebar-scrim').click({ position: { x: 320, y: 400 } })
  await expect(page.locator('.sidebar')).toHaveCSS('width', '64px')
  await button(page, '展开侧边栏').click()
  await page.getByRole('link', { name: '插件管理' }).click()
  await expect(page.getByRole('heading', { name: '插件管理', exact: true })).toBeVisible()
  await expect(page.locator('.sidebar')).toHaveCSS('width', '64px')
  await button(page, '新建插件').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  const rect = await dialog.boundingBox()
  expect(rect!.width).toBeLessThanOrEqual(358)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(button(page, '新建插件')).toBeFocused()
  expect(errors).toEqual([])
})

test('unsaved editor cancel, nested focus, route leave and logout preserve draft', async ({
  page,
}) => {
  const errors = await fixtures(page)
  await page.goto('/channels')
  await button(page, '新建渠道').click()
  await page.getByRole('textbox', { name: '名称', exact: true }).fill('未保存的渠道')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: '放弃未保存的修改？' })).toBeVisible()
  await button(page, '继续编辑').click()
  await expect(page.getByRole('textbox', { name: '名称', exact: true })).toHaveValue('未保存的渠道')
  for (let i = 0; i < 12; i++) {
    await page.keyboard.press('Tab')
    expect(await page.evaluate(() => !!document.activeElement?.closest('fluent-dialog'))).toBe(true)
  }
  // Router navigation is deliberately exercised while an editor owns the modal layer.
  const pending = routeTo(page, '/models')
  await expect(page.getByRole('dialog', { name: '放弃未保存的修改？' })).toBeVisible()
  await button(page, '继续编辑').click()
  await pending
  await expect(page).toHaveURL(/\/channels$/)
  await expect(page.getByRole('textbox', { name: '名称', exact: true })).toHaveValue('未保存的渠道')
  // Click through the DOM to exercise the sidebar's actual logout handler behind a modal.
  await page
    .locator('fluent-button[aria-label="退出登录"]')
    .evaluate((e) => (e as HTMLElement).click())
  await button(page, '继续编辑').click()
  expect(await page.evaluate(() => localStorage.getItem('admin_key'))).toBe('fixture-key')
  await page.keyboard.press('Escape')
  await button(page, '放弃修改').click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(button(page, '新建渠道')).toBeFocused()
  expect(errors).toEqual([])
})

test('channel form number/select/header values preserve request contract', async ({ page }) => {
  const errors = await fixtures(page)
  await page.goto('/channels')
  await button(page, '新建渠道').click()
  await page.getByRole('textbox', { name: '名称', exact: true }).fill('新渠道')
  await select(page, '提供商', 'Anthropic')
  await expect(page.getByRole('combobox', { name: '上游接口类型' })).toHaveText(/Claude Messages/)
  await page.getByRole('textbox', { name: 'Base URL', exact: true }).fill('https://example.org')
  await page.getByRole('textbox', { name: 'API Key', exact: true }).fill('test-upstream')
  await page.getByRole('spinbutton', { name: '超时 (秒)', exact: true }).fill('45')
  await page.getByRole('spinbutton', { name: '默认权重', exact: true }).fill('2.5')
  await page.getByRole('textbox', { name: '上游模型列表', exact: true }).fill('model-a\nmodel-b')
  await button(page, 'Accept: JSON').click()
  const req = page.waitForRequest(
    (r) => r.url().endsWith('/api/admin/channels') && r.method() === 'POST'
  )
  await button(page, '保存').click()
  const request = await req
  expect(request.postDataJSON()).toMatchObject({
    name: '新渠道',
    provider: 'anthropic',
    api_type: 'claude',
    timeout: 45,
    default_weight: 2.5,
    upstream_models: ['model-a', 'model-b'],
    custom_headers: { Accept: 'application/json' },
  })
  expect(request.headers()['x-admin-signature']).toBeTruthy()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('global messages stack, pause independently, persist across routes, and close', async ({
  page,
}) => {
  const errors = await fixtures(page)
  await page.goto('/channels')
  await page.clock.install()
  await page.evaluate(async () => {
    const { notify } = await import(/* @vite-ignore */ '/src/composables/useFeedback.ts')
    for (let i = 1; i <= 6; i++)
      notify(`消息 ${i}`, i === 6 ? 'error' : 'success', i === 6 ? 0 : 3500)
  })
  await expect(page.locator('.message-item')).toHaveCount(5)
  await expect(page.getByText('消息 1', { exact: true })).toHaveCount(0)
  await page.getByText('消息 2', { exact: true }).hover()
  await page.clock.runFor(3600)
  await expect(page.locator('.message-item')).toHaveCount(2)
  const path = routeTo(page, '/models')
  await page.clock.runFor(500)
  await path
  await expect(page.getByText('消息 2', { exact: true })).toBeVisible()
  await page.mouse.move(1000, 700)
  await page.clock.runFor(3600)
  await expect(page.locator('.message-item')).toHaveCount(1)
  await expect(page.getByRole('alert')).toHaveText('消息 6')
  await button(page, '关闭消息').click()
  await page.clock.runFor(200)
  await expect(page.locator('.message-item')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('query-only navigation keeps the draft and rapid paths settle correctly', async ({ page }) => {
  const errors = await fixtures(page)
  await page.goto('/playground')
  await page.getByRole('textbox', { name: '用户消息', exact: true }).fill('保留草稿')
  await routeTo(page, '/playground?probe=1')
  await expect(page.getByRole('textbox', { name: '用户消息', exact: true })).toHaveValue('保留草稿')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('textbox', { name: '用户消息', exact: true }).fill('')
  await page.evaluate(async () => {
    const router = (document.getElementById('app') as any).__vue_app__.config.globalProperties
      .$router
    router.push('/models')
    router.push('/channels')
    await router.push('/logs')
  })
  await expect(page.getByRole('heading', { name: '请求日志', exact: true })).toBeVisible()
  await expect(page.locator('.navigation-item[aria-current="page"]')).toHaveText('请求日志')
  expect(errors).toEqual([])
})

test('failure/retry and reduced motion remain functional', async ({ page }) => {
  const errors = await fixtures(page)
  await page.emulateMedia({ reducedMotion: 'reduce' })
  let fail = true
  await page.route('**/api/admin/channels', (route) =>
    route.fulfill(fail ? { status: 500, json: {} } : { json: { data: [] } })
  )
  await page.goto('/channels')
  await expect(page.getByRole('alert')).toContainText('加载失败')
  fail = false
  await button(page, '重试').click()
  await expect(page.getByText('暂无数据', { exact: true })).toBeVisible()
  await expect(page.locator('.app-layout')).toHaveCSS('transition-duration', '0s')
  await button(page, '收起侧边栏').click()
  await expect(page.locator('.sidebar')).toHaveCSS('width', '64px')
  expect(errors).toEqual([])
})

test('API key checkboxes, expiry, quota and model restrictions submit unchanged fields', async ({
  page,
}) => {
  const errors = await fixtures(page)
  await page.goto('/api-keys')
  await button(page, '新建密钥').click()
  await page.getByRole('textbox', { name: '名称', exact: true }).fill('限定密钥')
  await page.getByRole('checkbox', { name: '永不过期', exact: true }).click()
  await expect(page.getByRole('checkbox', { name: '永不过期', exact: true })).not.toBeChecked()
  await page.locator('fluent-text-field[aria-label="到期时间"] input').fill('2027-01-01T10:30')
  await page.getByRole('spinbutton', { name: 'Token 配额 (0 = 无限)', exact: true }).fill('500')
  await page.getByRole('checkbox', { name: '不限制（可调用所有模型）', exact: true }).click()
  await expect(
    page.getByRole('checkbox', { name: '不限制（可调用所有模型）', exact: true })
  ).not.toBeChecked()
  await select(page, '选择模型添加...', 'model-a')
  await button(page, '添加').click()
  await page.getByRole('checkbox', { name: '不限频', exact: true }).click()
  await expect(page.getByRole('checkbox', { name: '不限频', exact: true })).not.toBeChecked()
  await page.getByRole('spinbutton', { name: '频率限制（请求/分钟）', exact: true }).fill('20')
  const requestPromise = page.waitForRequest(
    (r) => r.url().endsWith('/api/admin/api-keys') && r.method() === 'POST'
  )
  await page.route('**/api/admin/api-keys', async (route) => {
    await route.fulfill({
      json: route.request().method() === 'POST' ? { key: 'sk-new-fixture' } : { data: [key] },
    })
  })
  await button(page, '保存').click()
  const data = (await requestPromise).postDataJSON()
  expect(data).toEqual({
    name: '限定密钥',
    expires_at: '2027-01-01T02:30:00.000Z',
    max_tokens: 500,
    allowed_models: ['model-a'],
    rate_limit: 20,
  })
  await expect(page.getByRole('dialog', { name: 'API 密钥已创建', exact: true })).toBeVisible()
  await expect(page.getByText('sk-new-fixture', { exact: true })).toBeVisible()
  expect(errors).toEqual([])
})

test('model editing preserves routing payload and independently saves channel targets', async ({
  page,
}) => {
  const errors = await fixtures(page)
  await page.goto('/models')
  await more(page)
  await page.getByRole('menuitem', { name: '编辑', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '编辑模型', exact: true })).toBeVisible()
  await page.getByRole('textbox', { name: '显示名称', exact: true }).fill('修改后的模型')
  await select(page, '分配策略', '加权')
  await page.getByRole('checkbox', { name: '启用自动容灾顺延' }).click()
  await expect(page.getByRole('checkbox', { name: '启用自动容灾顺延' })).not.toBeChecked()
  await select(page, '渠道', '主渠道（默认权重 1）')
  await expect(page.getByRole('combobox', { name: '上游模型 ID', exact: true })).toHaveText(
    /model-a/
  )
  const targetPromise = page.waitForRequest(
    (r) => r.url().endsWith('/api/admin/models/m-1/channels') && r.method() === 'POST'
  )
  await button(page, '添加路由目标').click()
  expect((await targetPromise).postDataJSON()).toEqual({
    type: 'reference',
    priority: 0,
    weight: 1,
    upstream_model_id: 'model-a',
    channel_id: 'ch-1',
  })
  const modelPromise = page.waitForRequest(
    (r) => r.url().endsWith('/api/admin/models/m-1') && r.method() === 'PUT'
  )
  await button(page, '保存').click()
  expect((await modelPromise).postDataJSON()).toEqual({
    name: 'model-a',
    display_name: '修改后的模型',
    routing_strategy: 'weighted',
    custom_js: '',
    failover_enabled: false,
    is_listed: true,
    supports_thinking: true,
    default_thinking_effort: 'none',
    claude_thinking_mode: 'adaptive',
  })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('plugin validation, deletion confirmation and focus restore', async ({ page }) => {
  const errors = await fixtures(page)
  let deleted = false
  await page.route('**/api/admin/plugins/p-1', async (route) => {
    deleted = route.request().method() === 'DELETE'
    await route.fulfill({ json: {} })
  })
  await page.goto('/plugins')
  await button(page, '新建插件').click()
  await page.getByRole('textbox', { name: '配置 (JSON)', exact: true }).fill('{invalid}')
  await button(page, '保存').click()
  await expect(page.getByRole('status')).toContainText('配置JSON格式错误')
  await expect(page.getByRole('dialog', { name: '新建插件' })).toBeVisible()
  await page.getByRole('textbox', { name: '配置 (JSON)', exact: true }).fill('{}')
  await button(page, '取消').click()
  await more(page)
  await page.getByRole('menuitem', { name: '删除', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '确认删除', exact: true })).toBeVisible()
  await button(page, '取消').click()
  expect(deleted).toBe(false)
  await expect(button(page, '更多操作')).toBeFocused()
  await more(page)
  await page.getByRole('menuitem', { name: '删除', exact: true }).click()
  await button(page, '删除').click()
  await expect.poll(() => deleted).toBe(true)
  expect(errors).toEqual([])
})

test('config number and boolean controls preserve typed values', async ({ page }) => {
  const errors = await fixtures(page)
  await page.goto('/config')
  const numericRow = page
    .locator('fluent-data-grid-row')
    .filter({ hasText: 'default_channel_timeout' })
  await numericRow.getByRole('button', { name: '更多操作' }).click()
  await page.getByRole('menuitem', { name: '编辑', exact: true }).click()
  await page.getByRole('spinbutton', { name: '值', exact: true }).fill('40')
  const number = page.waitForRequest(
    (r) => r.url().endsWith('/config/default_channel_timeout') && r.method() === 'PUT'
  )
  await button(page, '保存').click()
  expect((await number).postDataJSON()).toEqual({ value: 40 })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  const boolRow = page.locator('fluent-data-grid-row').filter({ hasText: 'log_body' })
  await boolRow.getByRole('button', { name: '更多操作' }).click()
  await page.getByRole('menuitem', { name: '编辑', exact: true }).click()
  await page.getByRole('checkbox', { name: '启用', exact: true }).click()
  await expect(page.getByRole('checkbox', { name: '启用', exact: true })).toBeChecked()
  const bool = page.waitForRequest(
    (r) => r.url().endsWith('/config/log_body') && r.method() === 'PUT'
  )
  await button(page, '保存').click()
  expect((await bool).postDataJSON()).toEqual({ value: true })
  expect(errors).toEqual([])
})

test('logs filters, pagination and detail keep existing API parameters', async ({ page }) => {
  const errors = await fixtures(page)
  await page.goto('/logs')
  await select(page, 'API 类型', 'Claude')
  await page.getByRole('textbox', { name: '模型', exact: true }).fill('model-a')
  await page.getByRole('textbox', { name: '调用密钥', exact: true }).fill('key-demo')
  await page.getByRole('spinbutton', { name: '状态码', exact: true }).fill('200')
  let req = page.waitForRequest('**/api/admin/logs?**')
  await button(page, '查询').click()
  let params = new URL((await req).url()).searchParams
  expect(Object.fromEntries(params)).toEqual({
    page: '1',
    page_size: '20',
    api_type: 'claude',
    model: 'model-a',
    from_apikey: 'key-demo',
    status: '200',
  })
  req = page.waitForRequest('**/api/admin/logs?**')
  await button(page, '下一页').click()
  params = new URL((await req).url()).searchParams
  expect(params.get('page')).toBe('2')
  await more(page)
  await page.getByRole('menuitem', { name: '详情', exact: true }).click()
  await expect(page.locator('fluent-dialog[aria-label="请求详情"]')).toContainText('测试输出')
  await page.keyboard.press('Escape')
  expect(errors).toEqual([])
})

for (const [label, apiType, response] of [
  [
    'OpenAI Completions',
    'openai',
    { choices: [{ delta: { reasoning_content: '推理', content: '测试回复' } }] },
  ],
  ['OpenAI Responses', 'responses', { type: 'response.output_text.delta', delta: '测试回复' }],
  [
    'Claude Messages',
    'claude',
    { type: 'content_block_delta', delta: { type: 'text_delta', text: '测试回复' } },
  ],
] as const) {
  test(`playground ${label} retains streaming request/response behavior`, async ({ page }) => {
    const errors = await fixtures(page)
    let payload: any
    await page.route('**/api/admin/playground', async (route) => {
      payload = route.request().postDataJSON()
      await route.fulfill({
        contentType: 'text/event-stream',
        body: `data: ${JSON.stringify(response)}\n\ndata: [DONE]\n\n`,
      })
    })
    await page.goto('/playground')
    await select(page, 'API 协议', label)
    await page.getByRole('textbox', { name: 'System / Instructions', exact: true }).fill('系统测试')
    await page.getByRole('textbox', { name: '用户消息', exact: true }).fill('你好')
    await button(page, '发送').click()
    await expect(page.getByText('测试回复', { exact: true })).toBeVisible()
    expect(payload).toMatchObject({ model: 'model-a', stream: true, _api_type: apiType })
    if (apiType === 'responses')
      expect(payload).toMatchObject({
        instructions: '系统测试',
        input: [{ role: 'user', content: '你好' }],
      })
    else if (apiType === 'claude')
      expect(payload).toMatchObject({
        system: '系统测试',
        messages: [{ role: 'user', content: '你好' }],
      })
    else
      expect(payload).toMatchObject({
        messages: [
          { role: 'system', content: '系统测试' },
          { role: 'user', content: '你好' },
        ],
      })
    if (apiType === 'openai') await expect(page.getByText('推理', { exact: true })).toBeVisible()
    await button(page, '清空对话').click()
    await button(page, '取消').click()
    await expect(page.getByText('测试回复', { exact: true })).toBeVisible()
    expect(errors).toEqual([])
  })
}

test('channel probe checkboxes and prompt health settings retain their payloads', async ({
  page,
}) => {
  const errors = await fixtures(page)
  await page.goto('/channels')
  await more(page)
  await page.getByRole('menuitem', { name: '测试', exact: true }).click()
  await page.getByRole('checkbox', { name: 'model-a', exact: true }).click()
  await expect(page.getByRole('checkbox', { name: 'model-a', exact: true })).toBeChecked()
  const probe = page.waitForRequest('**/api/admin/channels/ch-1/test')
  await button(page, '开始测试').click()
  expect((await probe).postDataJSON()).toEqual({
    model: 'model-a',
    message: 'Hi, please respond with a short greeting to confirm you are working.',
  })
  await expect(page.getByText('hello', { exact: true })).toBeVisible()
  await button(page, '关闭').click()
  await button(page, '新建渠道').click()
  await page.getByRole('textbox', { name: '上游模型列表', exact: true }).fill('model-a')
  await select(page, '检测模式', 'Prompt 探测')
  await expect(page.getByRole('combobox', { name: '探测模型', exact: true })).toHaveText(/model-a/)
  await page.getByRole('textbox', { name: '上游模型列表', exact: true }).fill('')
  await button(page, '保存').click()
  await expect(page.getByRole('status')).toContainText('Prompt 探测需要先配置上游模型')
  expect(errors).toEqual([])
})

test('keyboard-focused messages pause for their remaining time and semantic defaults differ', async ({
  page,
}) => {
  await fixtures(page)
  await page.goto('/channels')
  await page.clock.install()
  await page.evaluate(async () => {
    const { notify } = await import(/* @vite-ignore */ '/src/composables/useFeedback.ts')
    notify('成功默认时长')
    notify('警告默认时长', 'warning')
    notify('错误默认时长', 'error')
  })
  await page.clock.runFor(1000)
  await button(page, '关闭消息').first().focus()
  await page.clock.runFor(2700)
  await expect(page.getByText('成功默认时长', { exact: true })).toBeVisible()
  await expect(page.locator('.message-item')).toHaveCount(3)
  await button(page, '刷新').focus()
  await page.clock.runFor(2700)
  await expect(page.locator('.message-item')).toHaveCount(2)
  await page.clock.runFor(2000)
  await expect(page.locator('.message-item')).toHaveCount(0)
})

test('short mobile viewport, dark surfaces, Escape selection and Ctrl+S work', async ({ page }) => {
  const errors = await fixtures(page)
  await page.setViewportSize({ width: 375, height: 540 })
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.goto('/plugins')
  await button(page, '展开侧边栏').click()
  expect(await page.locator('.navigation').evaluate((e) => e.scrollHeight > e.clientHeight)).toBe(
    true
  )
  await page.screenshot({ path: 'test-results/mobile-dark-sidebar.png' })
  await page.keyboard.press('Escape')
  await button(page, '新建插件').click()
  await page.getByRole('textbox', { name: '名称', exact: true }).fill('键盘保存')
  await page.getByRole('combobox', { name: '钩子类型', exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: '新建插件', exact: true })).toBeVisible()
  await page.getByRole('textbox', { name: '模块路径', exact: true }).fill('app.plugins.Logging')
  const save = page.waitForRequest(
    (r) => r.url().endsWith('/api/admin/plugins') && r.method() === 'POST'
  )
  await page.getByRole('textbox', { name: '配置 (JSON)', exact: true }).fill('{"enabled":true}')
  await page.screenshot({ path: 'test-results/mobile-dark-editor.png' })
  await page.keyboard.press('Control+s')
  expect((await save).postDataJSON()).toMatchObject({
    name: '键盘保存',
    module_path: 'app.plugins.Logging',
    config: { enabled: true },
  })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(errors).toEqual([])
})
