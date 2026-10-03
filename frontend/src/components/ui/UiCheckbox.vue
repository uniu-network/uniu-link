<template>
  <fluent-checkbox :checked.prop="checked" :disabled="disabled || formBusy" @change="update"
    ><slot>{{ label }}</slot></fluent-checkbox
  >
</template>
<script setup lang="ts">
import { computed, inject } from 'vue'
import { formBusyKey } from '@/composables/useField'
const props = defineProps<{
  modelValue: boolean | string[]
  value?: string
  label?: string
  disabled?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: any] }>()
const formBusy = inject(
  formBusyKey,
  computed(() => false)
)
const checked = computed(() =>
  Array.isArray(props.modelValue) ? props.modelValue.includes(props.value || '') : props.modelValue
)
function update(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  emit(
    'update:modelValue',
    Array.isArray(props.modelValue)
      ? checked
        ? [...new Set([...props.modelValue, props.value || ''])]
        : props.modelValue.filter((v) => v !== props.value)
      : checked
  )
}
</script>
