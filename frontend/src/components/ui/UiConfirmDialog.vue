<template>
  <UiModal :open="feedback.confirmState.open" :title="feedback.confirmState.options.title" width="420px" @update:open="feedback.resolveConfirm(false)">
    <p class="text-sm text-muted-foreground">{{ feedback.confirmState.options.content }}</p>
    <template #footer>
      <div class="flex justify-end gap-2">
        <UiButton @click="feedback.resolveConfirm(false)">{{ feedback.confirmState.options.negativeText || '取消' }}</UiButton>
        <UiButton :variant="feedback.confirmState.options.variant === 'danger' ? 'danger' : 'primary'" @click="feedback.resolveConfirm(true)">
          {{ feedback.confirmState.options.positiveText || '确定' }}
        </UiButton>
      </div>
    </template>
  </UiModal>
</template>

<script setup lang="ts">
import { inject } from 'vue'
import { feedbackKey } from '@/composables/useFeedback'
import UiButton from './UiButton.vue'
import UiModal from './UiModal.vue'

const feedback = inject(feedbackKey)
if (!feedback) throw new Error('Feedback provider is missing')
</script>
