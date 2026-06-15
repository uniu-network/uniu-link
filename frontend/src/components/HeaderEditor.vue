<template>
  <div class="space-y-3">
    <div v-if="items.length" class="space-y-2">
      <div v-for="(item, index) in items" :key="index" class="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
        <input v-model="item.key" placeholder="Header 名称" class="h-8 rounded-md border border-input bg-background px-2 text-sm outline-none focus:ring-2 focus:ring-ring" />
        <input v-model="item.value" placeholder="Header 值" class="h-8 rounded-md border border-input bg-background px-2 text-sm outline-none focus:ring-2 focus:ring-ring" />
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
