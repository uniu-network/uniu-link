<script setup lang="ts">
withDefaults(defineProps<{ name: string; size?: number }>(), { size: 20 })
const paths: Record<string, string> = {
  gateway:
    'm10 13 4-4M8 16l-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0M16 8l1-1a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0',
  dashboard: 'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
  server: 'M3 3h18v7H3zM3 14h18v7H3zM7 6.5h.01M7 17.5h.01',
  model: 'M6 6h12v12H6zM9 9h6v6H9zM9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4',
  key: 'M15 7a5 5 0 1 1-2 8L6 22H2v-4l7-7a5 5 0 0 1 6-8M16 8h.01',
  plugin:
    'M9 3v3a3 3 0 1 0 6 0V3h6v6h-3a3 3 0 1 0 0 6h3v6h-6v-3a3 3 0 1 0-6 0v3H3v-6h3a3 3 0 1 0 0-6H3V3z',
  refresh: 'M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 14 6M18 18A8 8 0 0 1 4 12',
  plus: 'M12 5v14M5 12h14',
  more: 'M12 5h.01M12 12h.01M12 19h.01',
  menu: 'M4 6h16M4 12h16M4 18h16',
  close: 'M6 6l12 12M6 18 18 6',
  success: 'M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0M7 12l3 3 7-7',
  error: 'M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0M12 7v6M12 17h.01',
  warning: 'M12 3 2 21h20L12 3zM12 9v5M12 18h.01',
  monitor: 'M3 4h18v13H3zM12 17v4M8 21h8',
  sun: 'M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M5 19l1.5-1.5M17.5 6.5 19 5',
  moon: 'M21 13a9 9 0 0 1-10-10A9 9 0 1 0 21 13z',
  home: 'm3 11 9-8 9 8M5 9v12h5v-7h4v7h5V9',
  document: 'M6 3h8l4 4v14H6zM14 3v5h4M9 12h6M9 16h6',
  comment: 'M4 4h16v12H9l-5 4zM8 8h8M8 12h5',
  folder: 'M3 6h7l2 2h9v12H3zM3 6V4h6l2 2',
  tag: 'M3 4h8l10 10-7 7L3 10zM7 8h.01',
  image: 'M3 4h18v16H3zM3 16l5-5 4 4 3-3 6 6M15 8h.01',
  people:
    'M16 21v-3a5 5 0 0 0-10 0v3M20 21v-3a5 5 0 0 0-3-4M11 10a4 4 0 1 0 0-8 4 4 0 0 0 0 8M17 3a4 4 0 0 1 0 7',
  settings:
    'm9 3-.7 2.5-2.1 1.2-2.5-.6-2 3.4 1.8 1.9v2.4l-1.8 1.9 2 3.4 2.5-.6 2.1 1.2L9 22h4l.7-3.3 2.1-1.2 2.5.6 2-3.4-1.8-1.9v-2.4l1.8-1.9-2-3.4-2.5.6-2.1-1.2L13 3zM14.5 12a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0',
  person: 'M5 21v-3a7 7 0 0 1 14 0v3M16 6a4 4 0 1 1-8 0 4 4 0 0 1 8 0',
  logout: 'M10 3H4v18h6M8 12h13m-5-5 5 5-5 5',
  book: 'M12 5v16M12 5C9 2 5 2 2 4v15c3-2 7-2 10 2M12 5c3-3 7-3 10-1v15c-3-2-7-2-10 2',
}
</script>
<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.5"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <path :d="paths[name] || paths.document" />
  </svg>
</template>
