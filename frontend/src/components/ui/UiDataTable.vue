<template>
  <div class="overflow-hidden rounded-xl border border-border bg-card">
    <div class="overflow-x-auto thin-scrollbar">
      <table class="w-full min-w-max text-left text-sm">
        <thead class="bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th v-for="column in columns" :key="column.key" class="whitespace-nowrap px-4 py-3 font-medium">
              {{ column.title }}
            </th>
          </tr>
        </thead>
        <tbody class="divide-y divide-border">
          <tr v-for="(row, rowIndex) in data" :key="row.id || rowIndex" class="transition-colors hover:bg-muted/40">
            <td v-for="column in columns" :key="column.key" class="px-4 py-3 align-top">
              <component v-if="column.render" :is="{ render: () => column.render?.(row) }" />
              <span v-else>{{ row[column.key] ?? '-' }}</span>
            </td>
          </tr>
          <tr v-if="!data.length">
            <td :colspan="columns.length" class="px-4 py-10 text-center text-muted-foreground">暂无数据</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { VNode } from 'vue'

export interface UiTableColumn {
  title: string
  key: string
  render?: (row: any) => VNode | string | number | null
}

defineProps<{ columns: UiTableColumn[]; data: any[] }>()
</script>
