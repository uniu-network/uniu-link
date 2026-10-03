<template>
  <fluent-card class="ui-card">
    <header v-if="$slots.header || title" class="card-heading">
      <div class="card-heading-title">
        <component :is="icon" v-if="icon" :size="20" :stroke-width="1.5" aria-hidden="true" />
        <h2 v-if="title">{{ title }}</h2>
        <slot name="header" />
      </div>
      <slot name="extra" />
    </header>
    <div :class="{ 'panel-body': padded }"><slot /></div>
    <footer v-if="$slots.footer" class="card-footer">
      <fluent-divider />
      <div class="panel-body"><slot name="footer" /></div>
    </footer>
  </fluent-card>
</template>
<script setup lang="ts">
import type { Component } from 'vue'
withDefaults(defineProps<{ title?: string; padded?: boolean; icon?: Component }>(), {
  padded: true,
})
</script>
