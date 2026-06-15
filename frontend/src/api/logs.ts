import api from './client'

export async function listLogs(params?: Record<string, any>) {
  const res = await api.get('/logs', { params })
  return res.data
}
