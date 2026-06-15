import api from './client'

export async function listModels() {
  const res = await api.get('/models')
  return res.data
}

export async function getModel(id: string) {
  const res = await api.get(`/models/${id}`)
  return res.data
}

export async function createModel(data: Record<string, any>) {
  const res = await api.post('/models', data)
  return res.data
}

export async function updateModel(id: string, data: Record<string, any>) {
  const res = await api.put(`/models/${id}`, data)
  return res.data
}

export async function deleteModel(id: string) {
  const res = await api.delete(`/models/${id}`)
  return res.data
}

export async function listModelChannels(modelId: string) {
  const res = await api.get(`/models/${modelId}/channels`)
  return res.data
}

export async function addModelChannel(modelId: string, data: Record<string, any>) {
  const res = await api.post(`/models/${modelId}/channels`, data)
  return res.data
}

export async function updateModelChannel(modelId: string, refId: string, data: Record<string, any>) {
  const res = await api.put(`/models/${modelId}/channels/${refId}`, data)
  return res.data
}

export async function deleteModelChannel(modelId: string, refId: string) {
  const res = await api.delete(`/models/${modelId}/channels/${refId}`)
  return res.data
}
