import api from './client'

export async function listPlugins() {
  const res = await api.get('/plugins')
  return res.data
}

export async function createPlugin(data: Record<string, any>) {
  const res = await api.post('/plugins', data)
  return res.data
}

export async function updatePlugin(id: string, data: Record<string, any>) {
  const res = await api.put(`/plugins/${id}`, data)
  return res.data
}

export async function deletePlugin(id: string) {
  const res = await api.delete(`/plugins/${id}`)
  return res.data
}

export async function togglePlugin(id: string) {
  const res = await api.post(`/plugins/${id}/toggle`)
  return res.data
}
