<template>
  <div class="min-h-screen bg-background text-foreground">
    <aside class="fixed inset-y-0 left-0 z-40 hidden w-64 border-r border-border bg-card/80 backdrop-blur-xl lg:flex lg:flex-col">
      <div class="flex h-16 items-center gap-3 border-b border-border px-5">
        <div class="flex h-9 w-9 items-center justify-center rounded-xl border border-border bg-foreground text-background shadow-sm">
          <Zap class="h-5 w-5" />
        </div>
        <div>
          <p class="text-sm font-semibold tracking-tight">UniuLink</p>
          <p class="text-xs text-muted-foreground">AI Gateway</p>
        </div>
      </div>

      <nav class="flex-1 space-y-1 overflow-auto p-3 thin-scrollbar">
        <button
          v-for="item in menuItems"
          :key="item.key"
          class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm transition-all duration-150 hover:bg-accent"
          :class="activeKey === item.key ? 'bg-foreground text-background shadow-sm hover:bg-foreground' : 'text-muted-foreground hover:text-foreground'"
          @click="router.push(item.key)"
        >
          <component :is="item.icon" class="h-4 w-4" />
          <span>{{ item.label }}</span>
        </button>
      </nav>

      <div class="space-y-2 border-t border-border p-3">
        <UiButton variant="ghost" block @click="toggleTheme">
          <Sun v-if="isDark" class="h-4 w-4" />
          <Moon v-else class="h-4 w-4" />
          {{ isDark ? '浅色模式' : '深色模式' }}
        </UiButton>
        <UiButton variant="ghost" block @click="logout">
          <LogOut class="h-4 w-4" />
          退出登录
        </UiButton>
      </div>
    </aside>

    <div class="lg:pl-64">
      <header class="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-border bg-background/80 px-4 backdrop-blur-xl lg:px-8">
        <div>
          <h1 class="text-lg font-semibold tracking-tight">{{ route.meta?.title || 'UniuLink' }}</h1>
        </div>
        <div class="flex items-center gap-2 lg:hidden">
          <UiButton variant="ghost" size="icon" @click="toggleTheme">
            <Sun v-if="isDark" class="h-4 w-4" />
            <Moon v-else class="h-4 w-4" />
          </UiButton>
          <UiButton variant="ghost" size="icon" @click="logout"><LogOut class="h-4 w-4" /></UiButton>
        </div>
      </header>

      <main class="mx-auto w-full max-w-7xl p-4 lg:p-8">
        <slot />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  LayoutDashboard,
  Server,
  Cpu,
  FileText,
  Puzzle,
  LogOut,
  Zap,
  MessageSquareText,
  KeyRound,
  Settings,
  Sun,
  Moon,
} from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import { useTheme } from '@/composables/useTheme'
import UiButton from '@/components/ui/UiButton.vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const { isDark, toggleTheme } = useTheme()

const activeKey = computed(() => route.path)

const menuItems = [
  { label: '仪表盘', key: '/', icon: LayoutDashboard },
  { label: '渠道管理', key: '/channels', icon: Server },
  { label: '模型管理', key: '/models', icon: Cpu },
  { label: '演练场', key: '/playground', icon: MessageSquareText },
  { label: '请求日志', key: '/logs', icon: FileText },
  { label: 'API 密钥', key: '/api-keys', icon: KeyRound },
  { label: '插件管理', key: '/plugins', icon: Puzzle },
  { label: '系统配置', key: '/config', icon: Settings },
]

function logout() {
  authStore.logout()
  router.push('/login')
}
</script>
