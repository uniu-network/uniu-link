import { createRouter, createWebHistory } from 'vue-router'
import { guardUnsavedChanges, clearNavigationApproval } from '@/composables/useUnsavedChanges'
import { useAuthStore } from '@/stores/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
  },
  {
    path: '/',
    name: 'Dashboard',
    component: () => import('@/views/Dashboard.vue'),
    meta: { requiresAuth: true, title: '仪表盘' },
  },
  {
    path: '/channels',
    name: 'Channels',
    component: () => import('@/views/Channels.vue'),
    meta: { requiresAuth: true, title: '渠道管理' },
  },
  {
    path: '/accounts',
    name: 'Accounts',
    component: () => import('@/views/Accounts.vue'),
    meta: { requiresAuth: true, title: '账号管理' },
  },
  {
    path: '/models',
    name: 'Models',
    component: () => import('@/views/Models.vue'),
    meta: { requiresAuth: true, title: '模型管理' },
  },
  {
    path: '/playground',
    name: 'Playground',
    component: () => import('@/views/Playground.vue'),
    meta: { requiresAuth: true, title: '演练场' },
  },
  {
    path: '/logs',
    name: 'Logs',
    component: () => import('@/views/Logs.vue'),
    meta: { requiresAuth: true, title: '请求日志' },
  },
  {
    path: '/plugins',
    name: 'Plugins',
    component: () => import('@/views/Plugins.vue'),
    meta: { requiresAuth: true, title: '插件管理' },
  },
  {
    path: '/api-keys',
    name: 'ApiKeys',
    component: () => import('@/views/ApiKeys.vue'),
    meta: { requiresAuth: true, title: 'API 密钥' },
  },
  {
    path: '/config',
    name: 'Config',
    component: () => import('@/views/Config.vue'),
    meta: { requiresAuth: true, title: '系统配置' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to, from, next) => {
  if (to.path !== from.path && !(await guardUnsavedChanges())) return next(false)
  const authStore = useAuthStore()
  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    next('/login')
  } else if (to.path === '/login' && authStore.isAuthenticated) {
    next('/')
  } else {
    next()
  }
})

router.afterEach(clearNavigationApproval)
router.onError(clearNavigationApproval)

export default router
