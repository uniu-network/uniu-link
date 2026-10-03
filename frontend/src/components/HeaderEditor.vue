<template>
  <div class="space-y-3">
    <div v-if="items.length" class="space-y-2">
      <div v-for="(item, index) in items" :key="index" class="header-fields">
        <UiInput
          v-model="item.key"
          :aria-label="`第 ${index + 1} 个请求头名称`"
          placeholder="Header 名称"
          class="w-full"
        />
        <UiInput
          v-model="item.value"
          :aria-label="`第 ${index + 1} 个请求头值`"
          placeholder="Header 值"
          class="w-full"
        />
        <UiButton variant="link" size="sm" @click="remove(index)">删除</UiButton>
      </div>
    </div>
    <p v-else class="text-xs text-muted-foreground">暂无自定义请求头</p>

    <div class="flex flex-wrap gap-2">
      <UiButton size="sm" @click="add">+ 添加</UiButton>
      <UiButton size="sm" @click="applyPreset('User-Agent', '')">设置 UA</UiButton>
      <UiButton size="sm" @click="applyPreset('Referer', '')">设置 Referer</UiButton>
      <UiButton size="sm" @click="applyPreset('Accept', 'application/json')">Accept: JSON</UiButton>
    </div>
  </div>
</template>

<script setup lang="ts">
import UiInput from '@/components/ui/UiInput.vue'
import { computed } from 'vue'
import UiButton from '@/components/ui/UiButton.vue'

interface HeaderItem {
  key: string
  value: string
}

const props = defineProps<{
  modelValue: HeaderItem[]
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: HeaderItem[]): void
}>()

const items = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

function add() {
  emit('update:modelValue', [...items.value, { key: '', value: '' }])
}

function remove(index: number) {
  const next = [...items.value]
  next.splice(index, 1)
  emit('update:modelValue', next)
}

function applyPreset(key: string, value: string) {
  const next = [...items.value]
  const existing = next.find((item) => item.key.toLowerCase() === key.toLowerCase())
  if (existing) {
    existing.value = value
  } else {
    next.push({ key, value })
  }
  emit('update:modelValue', next)
}
</script>
