<template>
  <RouteProgress />
  <router-view v-slot="{ Component, route: viewRoute }">
    <Layout v-if="!isLoginPage">
      <Transition name="page" appear>
        <component :is="Component" :key="viewRoute.fullPath" />
      </Transition>
    </Layout>
    <Transition v-else name="page" appear>
      <component :is="Component" :key="viewRoute.fullPath" />
    </Transition>
  </router-view>
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
import { createFeedbackContext, feedbackKey } from '@/composables/useFeedback'

const route = useRoute()
const isLoginPage = computed(() => route.path === '/login')
provide(feedbackKey, createFeedbackContext())
</script>
