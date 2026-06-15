<template>
  <div class="fixed right-4 top-4 z-[70] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2">
    <TransitionGroup name="toast">
      <div v-for="toast in feedback.toasts" :key="toast.id" class="rounded-xl border bg-card p-4 text-sm shadow-vercel-sm animate-slide-in-right" :class="toastClass(toast.type)">
        <div class="flex items-start justify-between gap-3">
          <p>{{ toast.message }}</p>
          <button class="text-muted-foreground hover:text-foreground" @click="feedback.closeToast(toast.id)">x</button>
        </div>
      </div>
    </TransitionGroup>
  </div>
</template>

<script setup lang="ts">
import { inject } from 'vue'
import { feedbackKey } from '@/composables/useFeedback'

const feedback = inject(feedbackKey)
if (!feedback) throw new Error('Feedback provider is missing')

function toastClass(type: string) {
  if (type === 'success') return 'border-emerald-200 text-emerald-700 dark:border-emerald-500/30 dark:text-emerald-300'
  if (type === 'error') return 'border-red-200 text-red-700 dark:border-red-500/30 dark:text-red-300'
  if (type === 'warning') return 'border-amber-200 text-amber-700 dark:border-amber-500/30 dark:text-amber-300'
  return 'border-border text-foreground'
}
</script>
