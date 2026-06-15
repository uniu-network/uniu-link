<template>
  <section class="rounded-xl border border-border bg-card text-card-foreground shadow-sm transition-shadow duration-200 hover:shadow-vercel-sm">
    <header v-if="$slots.header || title" class="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
      <div>
        <h3 v-if="title" class="text-sm font-semibold tracking-tight">{{ title }}</h3>
        <slot name="header" />
      </div>
      <slot name="extra" />
    </header>
    <div :class="contentClass">
      <slot />
    </div>
    <footer v-if="$slots.footer" class="border-t border-border px-5 py-4">
      <slot name="footer" />
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{ title?: string; padded?: boolean }>(), { padded: true })
const contentClass = computed(() => props.padded ? 'p-5' : '')
</script>
