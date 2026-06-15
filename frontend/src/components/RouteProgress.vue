<template>
  <div class="fixed left-0 right-0 top-0 z-[80] h-0.5 overflow-hidden bg-transparent">
    <div class="h-full bg-foreground transition-all duration-200 ease-out" :style="barStyle" />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import router from '@/router'

const progress = ref(0)
const visible = ref(false)
let timer: number | undefined
let hideTimer: number | undefined

function start() {
  window.clearInterval(timer)
  window.clearTimeout(hideTimer)
  progress.value = 12
  visible.value = true
  timer = window.setInterval(() => {
    progress.value = Math.min(progress.value + Math.random() * 18, 82)
  }, 180)
}

function finish() {
  window.clearInterval(timer)
  window.clearTimeout(hideTimer)
  progress.value = 100
  hideTimer = window.setTimeout(() => {
    visible.value = false
    progress.value = 0
  }, 240)
}

const removeBeforeResolve = router.beforeResolve((to, from) => {
  if (to.fullPath !== from.fullPath) start()
})
const removeAfterEach = router.afterEach(finish)
const removeOnError = router.onError(finish)

onBeforeUnmount(() => {
  window.clearInterval(timer)
  window.clearTimeout(hideTimer)
  removeBeforeResolve()
  removeAfterEach()
  removeOnError()
})

const barStyle = computed(() => ({
  width: `${progress.value}%`,
  opacity: visible.value ? 1 : 0,
}))
</script>
