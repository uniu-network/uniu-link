<script setup lang="ts">
import { computed } from 'vue'
import { setThemePreference, themePreference, type ThemePreference } from '@/composables/useTheme'
import NavIcon from './NavIcon.vue'

defineProps<{ collapsed?: boolean }>()
const modes: ThemePreference[] = ['system', 'light', 'dark']
const labels = { system: '跟随系统', light: '浅色模式', dark: '深色模式' }
const icons = { system: 'monitor', light: 'sun', dark: 'moon' }
const next = computed(() => modes[(modes.indexOf(themePreference.value) + 1) % modes.length]!)
const description = computed(
  () => `当前主题：${labels[themePreference.value]}，点击切换为${labels[next.value]}`
)
</script>

<template>
  <fluent-button
    appearance="stealth"
    :aria-label="description"
    :title="description"
    @click="setThemePreference(next)"
  >
    <span class="sidebar-action-content"
      ><NavIcon :name="icons[themePreference]" /><span
        class="sidebar-action-label"
        :aria-hidden="collapsed"
        >{{ labels[themePreference] }}</span
      ></span
    >
  </fluent-button>
</template>
