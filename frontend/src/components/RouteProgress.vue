<template>
  <div v-if="visible" class="route-progress" role="status" aria-label="正在打开页面">
    <fluent-progress />
  </div>
</template>
<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import router from '@/router'
const visible = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
function finish() {
  clearTimeout(timer)
  visible.value = false
}
const removeBefore = router.beforeEach((to, from) => {
  if (to.path !== from.path)
    timer = setTimeout(() => {
      visible.value = true
    }, 150)
})
const removeAfter = router.afterEach(finish)
const removeError = router.onError(finish)
onBeforeUnmount(() => {
  finish()
  removeBefore()
  removeAfter()
  removeError()
})
</script>
