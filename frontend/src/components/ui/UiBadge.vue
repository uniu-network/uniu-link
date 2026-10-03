<template>
  <fluent-badge
    ><span class="badge-content"
      ><NavIcon
        v-if="semantic"
        :name="semantic"
        :size="16"
        :class="`message-symbol-${semantic}`" /><slot /></span
  ></fluent-badge>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import NavIcon from '@/components/NavIcon.vue'
const props = defineProps<{ variant?: 'default' | 'success' | 'danger' | 'warning' | 'info' }>()
const semantic = computed(() =>
  props.variant === 'danger'
    ? 'error'
    : props.variant === 'success' || props.variant === 'warning'
      ? props.variant
      : ''
)
</script>
