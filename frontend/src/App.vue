<template>
  <RouteProgress />
  <Layout v-if="!isLoginPage">
    <RouterView v-slot="{ Component, route: viewRoute }"
      ><Transition name="page" mode="out-in"
        ><div v-if="Component" :key="viewRoute.path" class="route-page">
          <component :is="Component" /></div></Transition
    ></RouterView>
  </Layout>
  <main v-else class="public-content">
    <RouterView v-slot="{ Component, route: viewRoute }"
      ><Transition name="page" mode="out-in"
        ><div v-if="Component" :key="viewRoute.path" class="route-page">
          <component :is="Component" /></div></Transition
    ></RouterView>
  </main>
  <UiToastViewport />
  <UiConfirmDialog />
</template>
<script setup lang="ts">
import { computed, provide } from 'vue'
import { useRoute } from 'vue-router'
import Layout from '@/components/Layout.vue'
import RouteProgress from '@/components/RouteProgress.vue'
import UiToastViewport from '@/components/ui/UiToastViewport.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { feedback, feedbackKey } from '@/composables/useFeedback'
const route = useRoute()
const isLoginPage = computed(() => route.path === '/login')
provide(feedbackKey, feedback)
</script>
