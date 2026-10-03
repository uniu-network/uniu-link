<template>
  <fluent-text-field
    v-bind="$attrs"
    :value.prop="String(modelValue ?? '')"
    :type="type"
    :aria-label="$attrs['aria-label'] || label || $attrs.placeholder"
    :disabled="disabled || formBusy"
    @input="update"
  />
</template>
<script setup lang="ts">
import { computed, inject } from 'vue'
import { fieldLabelKey, formBusyKey } from '@/composables/useField'
defineOptions({ inheritAttrs: false })
const props = withDefaults(
  defineProps<{
    modelValue?: string | number | null
    type?: string
    disabled?: boolean
    modelModifiers?: { number?: boolean; trim?: boolean }
  }>(),
  { type: 'text' }
)
const emit = defineEmits<{ 'update:modelValue': [value: any] }>()
const label = inject(
  fieldLabelKey,
  computed(() => '')
)
const formBusy = inject(
  formBusyKey,
  computed(() => false)
)
function update(event: Event) {
  let value: string | number = (event.target as HTMLInputElement).value
  if (props.modelModifiers?.trim) value = value.trim()
  if (props.modelModifiers?.number || props.type === 'number') {
    const number = parseFloat(value)
    if (!Number.isNaN(number)) value = number
  }
  emit('update:modelValue', value)
}
</script>
