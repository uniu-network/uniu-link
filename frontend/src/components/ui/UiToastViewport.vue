<template>
  <Teleport to="body">
    <TransitionGroup name="message" tag="div" class="message-stack" aria-label="消息提示">
      <Message
        v-for="item in feedback.toasts"
        :key="item.id"
        v-bind="item"
        @close="feedback.closeToast(item.id)"
      />
    </TransitionGroup>
  </Teleport>
</template>
<script setup lang="ts">
import Message from '@/components/Message.vue'
import { feedback } from '@/composables/useFeedback'
</script>
