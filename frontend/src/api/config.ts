import api from './client'

export async function listConfig() {
  const res = await api.get('/config')
  return res.data
}

export async function getConfig(key: string) {
  const res = await api.get(`/config/${key}`)
  return res.data
}

export async function updateConfig(key: string, value: any) {
  const res = await api.put(`/config/${key}`, { value })
  return res.data
}

export async function reloadConfig() {
  const res = await api.post('/config/reload')
  return res.data
}
