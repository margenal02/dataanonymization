const API_ROOT = '/api'

async function request(path, options = {}) {
  const response = await fetch(`${API_ROOT}${path}`, options)
  let data
  try {
    data = response.status === 204 ? null : await response.json()
  } catch {
    data = { detail: '服务返回了无法识别的响应。' }
  }
  if (!response.ok) {
    const error = new Error(data.detail || data.error_message || '请求失败，请稍后重试。')
    error.data = data
    throw error
  }
  return data
}

export const api = {
  listTasks: () => request('/tasks/'),
  getStats: () => request('/stats/'),
  anonymize(file, categories, customEntities) {
    const form = new FormData()
    form.append('file', file)
    form.append('categories', JSON.stringify(categories))
    form.append('custom_entities', customEntities)
    return request('/tasks/', { method: 'POST', body: form })
  },
  restore(taskId, file) {
    const form = new FormData()
    form.append('file', file)
    return request(`/tasks/${taskId}/restore/`, { method: 'POST', body: form })
  },
  deleteTask: taskId => request(`/tasks/${taskId}/`, {
    method: 'DELETE',
    headers: { 'X-Task-Delete-Confirm': taskId }
  })
}
