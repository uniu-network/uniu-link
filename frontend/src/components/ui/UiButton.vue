<template>
  <button
    :type="nativeType"
    :disabled="disabled || loading"
    :class="buttonClass"
  >
    <span v-if="loading" class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />
    <slot />
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { cn } from '@/lib/utils'

const props = withDefaults(defineProps<{
  variant?: 'default' | 'primary' | 'danger' | 'ghost' | 'link'
  size?: 'sm' | 'md' | 'lg' | 'icon'
  block?: boolean
  loading?: boolean
  disabled?: boolean
  nativeType?: 'button' | 'submit' | 'reset'
}>(), {
  variant: 'default',
  size: 'md',
  nativeType: 'button',
})

const variants = {
  default: 'border-border bg-background text-foreground hover:bg-accent',
  primary: 'border-primary bg-primary text-primary-foreground hover:bg-primary/90',
  danger: 'border-destructive bg-destructive text-destructive-foreground hover:bg-destructive/90',
  ghost: 'border-transparent bg-transparent hover:bg-accent',
  link: 'border-transparent bg-transparent px-0 text-foreground underline-offset-4 hover:underline',
}

const sizes = {
  sm: 'h-8 px-3 text-xs',
  md: 'h-9 px-4 text-sm',
  lg: 'h-10 px-5 text-sm',
  icon: 'h-9 w-9 p-0',
}

const buttonClass = computed(() => cn(
  'inline-flex items-center justify-center gap-2 rounded-md border font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50',
  variants[props.variant],
  sizes[props.size],
  props.block && 'w-full',
))
</script>
