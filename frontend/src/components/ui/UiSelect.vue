<template>
  <fluent-select
    v-bind="$attrs"
    ref="control"
    :value.prop="displayValue"
    :aria-label="$attrs['aria-label'] || label || placeholder"
    :disabled="disabled || formBusy || !options.length"
    @change="update"
  >
    <fluent-option v-if="showPlaceholder" value="" :selected.prop="true">{{
      options.length ? placeholder : '暂无选项'
    }}</fluent-option>
    <fluent-option
      v-for="option in options"
      :key="option.value"
      :value="option.value"
      :disabled="option.disabled"
      :selected.prop="option.value === displayValue && !option.disabled"
      ><span v-if="option.model || option.icon" slot="start" aria-hidden="true" class="option-icon">
        <ModelIcon :model="option.model" :icon="option.icon" :upstream-models="option.upstreamModels" :size="16" />
      </span>{{ option.label }}</fluent-option
    >
  </fluent-select>
</template>
<script setup lang="ts">
import { computed, inject, nextTick, ref, watch } from 'vue'
import { fieldLabelKey, formBusyKey } from '@/composables/useField'
import ModelIcon from '@/components/ModelIcon.vue'
defineOptions({ inheritAttrs: false })
export interface UiSelectOption {
  label: string
  value: string
  disabled?: boolean
  model?: string
  icon?: string
  upstreamModels?: string[]
}
const props = withDefaults(
  defineProps<{
    modelValue: string
    options: UiSelectOption[]
    placeholder?: string
    disabled?: boolean
  }>(),
  { placeholder: '请选择' }
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
const control = ref<HTMLElement & { value: string }>()
const displayValue = computed(() =>
  props.options.some((o) => o.value === props.modelValue && !o.disabled) ? props.modelValue : ''
)
// An enabled empty option avoids FAST 2.6.1's all-disabled selection recursion.
// Remove the placeholder after selection so it cannot diverge from the bound value.
const showPlaceholder = computed(
  () => !displayValue.value && !props.options.some((o) => o.value === '' && !o.disabled)
)
watch(
  () => [displayValue.value, props.options],
  async () => {
    await nextTick()
    if (control.value) control.value.value = displayValue.value
  },
  { immediate: true, deep: true }
)
function update(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  if (value !== props.modelValue && props.options.some((o) => o.value === value && !o.disabled))
    emit('update:modelValue', value)
}
</script>
