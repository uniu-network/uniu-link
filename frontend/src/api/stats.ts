import api from './client'

export async function getDashboardStats() {
  const res = await api.get('/stats')
  return res.data
}

export async function getCacheStats() {
  const res = await api.get('/cache/stats')
  return res.data
}

export async function clearCache(model?: string) {
  const res = await api.post('/cache/clear', null, {
    params: model ? { model } : {},
  })
  return res.data
}
