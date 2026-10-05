import { computed, readonly, ref } from 'vue'
import {
  accentBaseColor,
  baseLayerLuminance,
  controlCornerRadius,
  layerCornerRadius,
  StandardLuminance,
  SwatchRGB,
} from '@fluentui/web-components'

// One accent for the native sidebar and Fluent's adaptive color palette.
export const brandPink = '#f52d94'
export type ThemePreference = 'system' | 'light' | 'dark'
const storageKey = 'uniulink-admin-theme'
const preference = ref<ThemePreference>('system')
const systemDark = ref(false)
export const themePreference = readonly(preference)
export const resolvedTheme = computed(() =>
  preference.value === 'system' ? (systemDark.value ? 'dark' : 'light') : preference.value
)

function updateTheme(): void {
  const dark = resolvedTheme.value === 'dark'
  // Global defaults avoid introducing a per-element token inheritance cycle.
  baseLayerLuminance.withDefault(dark ? StandardLuminance.DarkMode : StandardLuminance.LightMode)
  document.documentElement.classList.toggle('dark', dark)
  document.documentElement.dataset.theme = resolvedTheme.value
  document.documentElement.style.colorScheme = resolvedTheme.value
}

export function setThemePreference(value: ThemePreference): void {
  preference.value = value
  try {
    localStorage.setItem(storageKey, value)
  } catch {
    /* Theme still works when storage is unavailable. */
  }
  updateTheme()
}

export function applyTheme(): void {
  controlCornerRadius.withDefault(6)
  layerCornerRadius.withDefault(12)
  const channel = (offset: number) => Number.parseInt(brandPink.slice(offset, offset + 2), 16) / 255
  accentBaseColor.withDefault(SwatchRGB.create(channel(1), channel(3), channel(5)))
  document.documentElement.style.setProperty('--brand-pink', brandPink)
  const system = window.matchMedia('(prefers-color-scheme: dark)')
  systemDark.value = system.matches
  try {
    const saved = localStorage.getItem(storageKey) || localStorage.getItem('theme')
    if (saved === 'light' || saved === 'dark' || saved === 'system') preference.value = saved
  } catch {
    /* Follow the system when storage is unavailable. */
  }
  const changed = (event: MediaQueryListEvent) => {
    systemDark.value = event.matches
    if (preference.value === 'system') updateTheme()
  }
  system.addEventListener('change', changed)
  if (import.meta.hot) import.meta.hot.dispose(() => system.removeEventListener('change', changed))
  updateTheme()
}

export function useTheme() {
  return {
    isDark: computed(() => resolvedTheme.value === 'dark'),
    themePreference,
    setThemePreference,
  }
}
