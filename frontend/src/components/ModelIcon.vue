<template>
  <span
    class="model-icon"
    :class="{ 'model-icon-framed': framed }"
    :style="{ '--model-icon-size': `${size}px` }"
    :data-brand="identity.id"
    role="img"
    :aria-label="identity.label"
    :title="identity.label"
  >
    <img
      v-if="identity.icon && failedIcon !== identity.icon"
      :src="identity.icon"
      :class="{ 'model-icon-monochrome': identity.monochrome }"
      alt=""
      aria-hidden="true"
      @error="failedIcon = identity.icon"
    />
    <NavIcon v-else name="model" :size="size" />
  </span>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import NavIcon from './NavIcon.vue'
import { resolveModelIdentity, resolveProviderIdentity } from '@/utils/modelIdentity'

const props = withDefaults(defineProps<{
  model?: string
  provider?: string
  icon?: string
  upstreamModels?: string[]
  size?: number
  framed?: boolean
}>(), { size: 20 })
const failedIcon = ref<string>()
const identity = computed(() => props.provider
  ? resolveProviderIdentity(props.provider)
  : resolveModelIdentity(props.model, props.upstreamModels, props.icon))
</script>
