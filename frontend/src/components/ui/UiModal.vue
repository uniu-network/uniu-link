<template>
  <Teleport to="body">
    <Transition name="modal-fade">
      <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4 backdrop-blur-sm" @click.self="$emit('update:open', false)">
        <section class="max-h-[90vh] w-full overflow-auto rounded-xl border border-border bg-card shadow-vercel animate-modal-in thin-scrollbar" :style="widthStyle">
          <header class="flex items-center justify-between border-b border-border px-5 py-4">
            <h3 class="text-sm font-semibold">{{ title }}</h3>
            <button class="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground" @click="$emit('update:open', false)">x</button>
          </header>
          <div class="p-5"><slot /></div>
          <footer v-if="$slots.footer" class="border-t border-border px-5 py-4"><slot name="footer" /></footer>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{ open: boolean; title?: string; width?: string }>(), { width: '600px' })
defineEmits<{ (e: 'update:open', value: boolean): void }>()
const widthStyle = computed(() => ({ maxWidth: props.width }))
</script>
