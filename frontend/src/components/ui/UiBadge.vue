<template>
  <span :class="badgeClass"><slot /></span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { cn } from '@/lib/utils'

const props = withDefaults(defineProps<{
  variant?: 'default' | 'info' | 'success' | 'warning' | 'danger' | 'primary'
}>(), { variant: 'default' })

const variants = {
  default: 'border-border bg-secondary text-secondary-foreground',
  info: 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-300',
  success: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300',
  warning: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300',
  danger: 'border-red-200 bg-red-50 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300',
  primary: 'border-foreground bg-foreground text-background',
}

const badgeClass = computed(() => cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium', variants[props.variant]))
</script>
