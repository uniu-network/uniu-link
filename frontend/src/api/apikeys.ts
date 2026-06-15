import api from './client'

export async function listApiKeys() {
  const res = await api.get('/api-keys')
  return res.data
}

export async function createApiKey(data: Record<string, any>) {
  const res = await api.post('/api-keys', data)
  return res.data
}

export async function updateApiKey(id: string, data: Record<string, any>) {
  const res = await api.put(`/api-keys/${id}`, data)
  return res.data
}

export async function deleteApiKey(id: string) {
  const res = await api.delete(`/api-keys/${id}`)
  return res.data
}

export async function toggleApiKey(id: string) {
  const res = await api.post(`/api-keys/${id}/toggle`)
  return res.data
}
