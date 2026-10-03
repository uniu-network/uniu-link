<template>
  <fluent-card class="ui-card">
    <div v-if="data.length" class="table-scroll" tabindex="0" :aria-label="label + '，可横向滚动'">
      <fluent-data-grid
        generate-header="none"
        :aria-label="label"
        :grid-template-columns="gridColumns"
        :style="{ minWidth: `${Math.max(760, columns.length * 140)}px` }"
        @keydown.capture="gridKeydown"
      >
        <fluent-data-grid-row row-type="header">
          <fluent-data-grid-cell
            v-for="(column, index) in columns"
            :key="column.key"
            cell-type="columnheader"
            :grid-column="String(index + 1)"
            >{{ column.title }}</fluent-data-grid-cell
          >
        </fluent-data-grid-row>
        <fluent-data-grid-row v-for="(row, rowIndex) in data" :key="row.id || row.key || rowIndex">
          <fluent-data-grid-cell
            v-for="(column, index) in columns"
            :key="column.key"
            :columnDefinition.prop="definitions[index]"
            :grid-column="String(index + 1)"
          >
            <div class="cell-content"><CellValue :column="column" :row="row" /></div>
          </fluent-data-grid-cell>
        </fluent-data-grid-row>
      </fluent-data-grid>
    </div>
    <UiEmpty v-else title="暂无数据" />
  </fluent-card>
</template>
<script setup lang="ts">
import { computed, defineComponent, type PropType, type VNode } from 'vue'
import UiEmpty from './UiEmpty.vue'
export interface UiTableColumn {
  title: string
  key: string
  render?: (row: any) => VNode | string | number | null
}
const props = withDefaults(
  defineProps<{ columns: UiTableColumn[]; data: any[]; label?: string }>(),
  { label: '数据列表' }
)
const definitions = computed(() =>
  props.columns.map((column) => ({
    columnDataKey: column.key,
    title: column.title,
    cellInternalFocusQueue: true,
    cellFocusTargetCallback: (cell: HTMLElement) =>
      cell.querySelector<HTMLElement>('fluent-button, fluent-anchor'),
  }))
)
function gridKeydown(event: KeyboardEvent) {
  // FAST's Ctrl+End assumes generated column definitions. This grid uses Vue slots.
  if (event.ctrlKey && event.key === 'End') {
    const cells = (event.currentTarget as HTMLElement).querySelectorAll<HTMLElement>(
      'fluent-data-grid-row:last-child > fluent-data-grid-cell'
    )
    cells[cells.length - 1]?.focus()
    event.preventDefault()
    event.stopPropagation()
  }
}
const gridColumns = computed(() =>
  props.columns
    .map((column) =>
      column.key === 'actions'
        ? '80px'
        : column.key === 'description' || column.key === 'base_url' || column.key === 'module_path'
          ? 'minmax(190px, 2fr)'
          : 'minmax(140px, 1fr)'
    )
    .join(' ')
)
const CellValue = defineComponent({
  props: {
    column: { type: Object as PropType<UiTableColumn>, required: true },
    row: { type: Object, required: true },
  },
  setup(props) {
    return () =>
      props.column.render
        ? props.column.render(props.row)
        : String(props.row[props.column.key] ?? '—')
  },
})
</script>
