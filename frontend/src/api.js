const API_ROOT = '/api'

async function request(path, options = {}) {
  const response = await fetch(`${API_ROOT}${path}`, options)
  let data = null
  try {
    const body = response.status === 204 ? '' : await response.text()
    data = body ? JSON.parse(body) : null
  } catch {
    const statusMessages = {
      413: '文件大小超过服务器上传限制，请选择较小文件或联系管理员调整上限。',
      502: '后端服务暂时不可用，请稍后重试并查看容器日志。',
      503: '模型或后端服务尚未就绪，请稍后重试。',
      504: '文件处理超时，请拆分文件后重试。'
    }
    data = { detail: statusMessages[response.status] || `服务返回异常响应（HTTP ${response.status}）。` }
  }
  if (!response.ok) {
    const error = new Error(data?.detail || data?.error_message || `请求失败（HTTP ${response.status}）。`)
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
