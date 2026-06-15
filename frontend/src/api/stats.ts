import api from './client'

export async function getDashboardStats() {
  const res = await api.get('/stats')
  return res.data
}
