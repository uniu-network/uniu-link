import api from './client'

export async function listChannels() {
  const res = await api.get('/channels')
  return res.data
}

export async function getChannel(id: string) {
  const res = await api.get(`/channels/${id}`)
  return res.data
}

export async function createChannel(data: Record<string, any>) {
  const res = await api.post('/channels', data)
  return res.data
}

export async function updateChannel(id: string, data: Record<string, any>) {
  const res = await api.put(`/channels/${id}`, data)
  return res.data
}

export async function deleteChannel(id: string) {
  const res = await api.delete(`/channels/${id}`)
  return res.data
}

export async function syncChannelModels(id: string) {
  const res = await api.post(`/channels/${id}/sync-models`)
  return res.data
}

export async function testChannel(id: string, model: string, message?: string) {
  const res = await api.post(`/channels/${id}/test`, { model, message })
  return res.data
}
