<template>
  <div class="app-layout" :class="{ 'sidebar-collapsed': collapsed }">
    <a class="skip-link" href="#main">跳转到主要内容</a>
    <Transition name="sidebar-scrim"
      ><div
        v-if="isNarrow && !collapsed"
        class="sidebar-scrim"
        aria-hidden="true"
        @click="collapsed = true"
    /></Transition>
    <aside class="sidebar" aria-label="管理侧边栏">
      <div class="sidebar-brand">
        <div class="sidebar-toggle">
          <fluent-button
            id="sidebar-toggle"
            appearance="stealth"
            :aria-label="collapsed ? '展开侧边栏' : '收起侧边栏'"
            :title="collapsed ? '展开侧边栏' : '收起侧边栏'"
            :aria-expanded="!collapsed"
            aria-controls="admin-navigation"
            @click="collapsed = !collapsed"
            ><NavIcon name="menu" :size="18"
          /></fluent-button>
        </div>
        <div class="brand-mark"><NavIcon name="gateway" :size="30" /></div>
        <div class="brand-copy" :aria-hidden="collapsed">
          <strong>UniuLink</strong><span>AI 网关管理后台</span>
        </div>
      </div>
      <nav id="admin-navigation" class="navigation" aria-label="管理导航">
        <section v-for="group in menuGroups" :key="group.label" class="navigation-group" :aria-label="group.label">
          <p class="navigation-group-label" :aria-hidden="collapsed">{{ group.label }}</p>
          <RouterLink
            v-for="item in group.items"
            :key="item.path"
            :to="item.path"
            class="navigation-item"
            :class="{ 'navigation-item-selected': selected(item.path) }"
            :aria-current="selected(item.path) ? 'page' : undefined"
            :aria-label="item.label"
            :title="collapsed ? item.label : undefined"
            @click="navigated"
            ><NavIcon :name="item.icon" /><span class="navigation-label" :aria-hidden="collapsed">{{
              item.label
            }}</span></RouterLink
          >
        </section>
      </nav>
      <div class="sidebar-footer">
        <div class="sidebar-action"><ThemeToggle :collapsed="collapsed" /></div>
        <div
          class="sidebar-account"
          role="group"
          :aria-label="collapsed ? '管理员，系统管理权限' : undefined"
          :title="collapsed ? '管理员 · 系统管理权限' : undefined"
        >
          <span class="sidebar-avatar" aria-hidden="true"><NavIcon name="person" /></span>
          <span class="account-copy" :aria-hidden="collapsed">
            <strong>管理员</strong><span>系统管理权限</span>
          </span>
        </div>
        <div class="sidebar-action">
          <fluent-button
            appearance="stealth"
            :disabled="signingOut"
            aria-label="退出登录"
            title="退出登录"
            @click="logout"
            ><span class="sidebar-action-content"
              ><NavIcon name="logout" /><span class="sidebar-action-label" :aria-hidden="collapsed"
                >退出登录</span
              ></span
            ></fluent-button
          >
        </div>
      </div>
    </aside>
    <main id="main" class="main-content" tabindex="-1" :inert="isNarrow && !collapsed"><slot /></main>
  </div>
</template>
<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { approveNextNavigation, confirmUnsavedChanges } from '@/composables/useUnsavedChanges'
import NavIcon from './NavIcon.vue'
import ThemeToggle from './ThemeToggle.vue'
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const screen = window.matchMedia('(max-width: 700px)')
const isNarrow = ref(screen.matches)
const collapsed = ref(screen.matches)
const signingOut = ref(false)
const menuGroups = [
  { label: '工作台', items: [
    { path: '/', label: '仪表盘', icon: 'dashboard' },
    { path: '/playground', label: '演练场', icon: 'comment' },
  ] },
  { label: '网关管理', items: [
    { path: '/channels', label: '渠道管理', icon: 'server' },
    { path: '/accounts', label: '账号管理', icon: 'key' },
    { path: '/models', label: '模型管理', icon: 'model' },
    { path: '/api-keys', label: 'API 密钥', icon: 'key' },
  ] },
  { label: '系统与观测', items: [
    { path: '/logs', label: '请求日志', icon: 'document' },
    { path: '/plugins', label: '插件管理', icon: 'plugin' },
    { path: '/config', label: '系统配置', icon: 'settings' },
  ] },
]
function selected(path: string) {
  return path === '/'
    ? route.path === '/'
    : route.path === path || route.path.startsWith(path + '/')
}
function navigated() {
  if (isNarrow.value) collapsed.value = true
}
function resized(event: MediaQueryListEvent) {
  isNarrow.value = event.matches
  collapsed.value = event.matches
}
function escaped(event: KeyboardEvent) {
  if (event.key === 'Escape' && isNarrow.value && !collapsed.value) {
    collapsed.value = true
    document.getElementById('sidebar-toggle')?.focus()
  }
}
screen.addEventListener('change', resized)
window.addEventListener('keydown', escaped)
onBeforeUnmount(() => {
  screen.removeEventListener('change', resized)
  window.removeEventListener('keydown', escaped)
})
async function logout() {
  if (signingOut.value) return
  signingOut.value = true
  try {
    if (!(await confirmUnsavedChanges())) return
    approveNextNavigation()
    auth.logout()
    await router.push('/login')
  } finally {
    signingOut.value = false
  }
}
</script>
