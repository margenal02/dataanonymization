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
  getModelRuntime: () => request('/model/runtime/'),
  setModelRuntime: mode => request('/model/runtime/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode })
  }),
  listLabels: () => request('/labels/'),
  createLabel: label => request('/labels/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(label)
  }),
  updateLabel: (labelId, label) => request(`/labels/${labelId}/`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(label)
  }),
  deleteLabel: labelId => request(`/labels/${labelId}/`, { method: 'DELETE' }),
  anonymize(file, categories, customEntities, uieMode) {
    const form = new FormData()
    form.append('file', file)
    form.append('categories', JSON.stringify(categories))
    form.append('custom_entities', customEntities)
    form.append('uie_mode', uieMode)
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
