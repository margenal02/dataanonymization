<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from './api'
import AppIcon from './components/AppIcon.vue'
import AnalyticsPanel from './components/AnalyticsPanel.vue'
import DocumentPreview from './components/DocumentPreview.vue'

const nav = ref('workspace')
const mode = ref('anonymize')
const tasks = ref([])
const stats = ref({ tasks: 0, completed: 0, restored: 0, entities: 0, training_examples: 0, active_labels: 0, max_upload_size_mb: 200 })
const loading = ref(false)
const loadingHistory = ref(false)
const deletingTaskId = ref('')
const error = ref('')
const result = ref(null)
const anonymizeFile = ref(null)
const restoreFile = ref(null)
const selectedTaskId = ref('')
const dragging = ref('')
const customEntities = ref('')
const uieMode = ref(localStorage.getItem('uieMode') || 'on_demand')
const modelRuntime = ref({ enabled: true, available: false, model: 'uie-base', resident_loaded: false })
const modelModeLoading = ref(false)
const trainingLabels = ref([])
const trainingExampleCount = ref(0)
const labelForm = ref({ text: '', category: 'person' })
const editingLabelId = ref('')
const editingLabel = ref({ text: '', category: 'person' })
const labelLoading = ref(false)
const reviewOpen = ref(false)
const reviewLoading = ref(false)
const reviewData = ref({ entities: [], preview: [], alias_groups: [], excluded_count: 0 })
const reviewAdditions = ref('')
const reviewSelectedTokens = ref([])
const reviewCategories = ref({})
const reviewAliasChoices = ref({})
const reviewQuery = ref('')
const reviewCategoryFilter = ref('all')
const reviewSelection = ref('')
const reviewSelectionLocation = ref('')
const reviewSelectionCategory = ref('organization')
const trainingDocuments = ref([])
const trainingDocumentFile = ref(null)
const activeTrainingDocument = ref(null)
const trainingDocumentLoading = ref(false)
const trainingSelectedKeys = ref([])
const trainingCategories = ref({})
const trainingAdditions = ref('')
const trainingSelection = ref('')
const trainingSelectionCategory = ref('organization')
const modelArtifacts = ref([])
const modelBase = ref({ name: 'uie-base', version: '内置', is_active: true })
const modelPackageMaxMb = ref(1024)
const modelPackageFile = ref(null)
const modelPackageForm = ref({ name: '', version: '' })
const modelPackageLoading = ref(false)
const processingProgress = ref(null)
const selectedCategories = ref(['organization', 'person', 'product', 'location', 'phone', 'id_card', 'email', 'address'])

const categoryOptions = [
  { key: 'organization', label: '单位 / 部门', icon: 'building' },
  { key: 'person', label: '人员姓名', icon: 'person' },
  { key: 'product', label: '品牌 / 产品', icon: 'product' },
  { key: 'location', label: '产区 / 地点', icon: 'location' },
  { key: 'phone', label: '联系电话', icon: 'phone' },
  { key: 'id_card', label: '证件号码', icon: 'id_card' },
  { key: 'email', label: '电子邮箱', icon: 'email' },
  { key: 'address', label: '地址信息', icon: 'address' }
]
const labelCategoryOptions = [...categoryOptions, { key: 'custom', label: '其他敏感项' }]

const completedTasks = computed(() => tasks.value.filter(task => ['completed', 'restored'].includes(task.status)))
const selectedTask = computed(() => tasks.value.find(task => task.id === selectedTaskId.value))
const maxUploadSizeMb = computed(() => Number(stats.value.max_upload_size_mb) || 200)
const pageMeta = computed(() => ({
  workspace: ['数据处理台', '安全处理、人工复核、可逆恢复'],
  history: ['处理记录', '文件状态与结果管理'],
  analytics: ['质量洞察', '识别质量与处理效率'],
  models: ['模型中心', '权重版本、导入导出与运行状态'],
  labels: ['训练标注', '机器预标与人工校正'],
  guide: ['使用说明', '三步完成安全数据处理']
})[nav.value] || ['数据处理台', '文件级敏感信息匿名化与安全恢复'])
const filteredReviewEntities = computed(() => {
  const query = reviewQuery.value.trim().toLocaleLowerCase('zh-CN')
  return reviewData.value.entities.filter(entity => (
    (reviewCategoryFilter.value === 'all' || entity.category === reviewCategoryFilter.value)
    && (!query || entity.text.toLocaleLowerCase('zh-CN').includes(query) || entity.token.toLocaleLowerCase('zh-CN').includes(query))
  ))
})

function formatBytes(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatDate(value) {
  const date = new Date(value)
  if (!value || Number.isNaN(date.getTime())) return '--'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false
  }).format(date)
}

function statusMeta(status) {
  return {
    processing: ['处理中', 'status-processing'],
    review: ['待人工确认', 'status-review'],
    completed: ['脱敏完成', 'status-completed'],
    restored: ['已生成正式版', 'status-restored'],
    failed: ['处理失败', 'status-failed']
  }[status] || [status, '']
}

function fileFromEvent(event, target) {
  const file = event.target.files?.[0] || event.dataTransfer?.files?.[0]
  if (!file) return
  if (file.size > maxUploadSizeMb.value * 1024 * 1024) {
    if (target === 'anonymize') anonymizeFile.value = null
    else restoreFile.value = null
    if (event.target && 'value' in event.target) event.target.value = ''
    error.value = `文件大小不能超过 ${maxUploadSizeMb.value} MB，当前文件为 ${formatBytes(file.size)}。`
    dragging.value = ''
    return
  }
  if (target === 'anonymize') anonymizeFile.value = file
  else restoreFile.value = file
  error.value = ''
  dragging.value = ''
}

async function refreshData() {
  loadingHistory.value = true
  try {
    const [taskData, statData] = await Promise.all([api.listTasks(), api.getStats()])
    tasks.value = taskData
    stats.value = statData
    if (!selectedTaskId.value && completedTasks.value.length) selectedTaskId.value = completedTasks.value[0].id
  } catch (e) {
    error.value = e.message
  } finally {
    loadingHistory.value = false
  }
}

async function refreshModelRuntime() {
  try {
    modelRuntime.value = await api.getModelRuntime()
  } catch (e) {
    modelRuntime.value = { enabled: true, available: false, model: 'uie-base', resident_loaded: false, detail: e.message }
  }
}

async function selectUieMode(nextMode) {
  uieMode.value = nextMode
  localStorage.setItem('uieMode', nextMode)
  if (!modelRuntime.value.enabled) return
  modelModeLoading.value = true
  error.value = ''
  try {
    modelRuntime.value = await api.setModelRuntime(nextMode)
  } catch (e) {
    error.value = e.message
  } finally {
    modelModeLoading.value = false
    await refreshModelRuntime()
  }
}

async function refreshLabels() {
  try {
    const data = await api.listLabels()
    trainingLabels.value = data.labels || []
    trainingExampleCount.value = data.training_example_count || 0
  } catch (e) {
    error.value = e.message
  }
}

async function refreshModelArtifacts() {
  try {
    const data = await api.listModelArtifacts()
    modelArtifacts.value = data.artifacts || []
    modelBase.value = data.base_model || modelBase.value
    modelPackageMaxMb.value = Number(data.max_package_size_mb) || 1024
  } catch (e) {
    error.value = e.message
  }
}

function fileFromModelPackageEvent(event) {
  const file = event.target.files?.[0] || event.dataTransfer?.files?.[0] || null
  if (file && file.size > modelPackageMaxMb.value * 1024 * 1024) {
    modelPackageFile.value = null
    if (event.target && 'value' in event.target) event.target.value = ''
    error.value = `模型包不能超过 ${modelPackageMaxMb.value} MB，当前文件为 ${formatBytes(file.size)}。`
    return
  }
  modelPackageFile.value = file
  if (file && !modelPackageForm.value.name) modelPackageForm.value.name = file.name.replace(/\.zip$/i, '')
  error.value = ''
}

async function importModelPackage() {
  if (!modelPackageFile.value) return
  modelPackageLoading.value = true
  error.value = ''
  try {
    await api.importModelArtifact(modelPackageFile.value, modelPackageForm.value.name, modelPackageForm.value.version)
    modelPackageFile.value = null
    modelPackageForm.value = { name: '', version: '' }
    await refreshModelArtifacts()
  } catch (e) {
    error.value = e.message
  } finally {
    modelPackageLoading.value = false
  }
}

async function activateModelPackage(artifact = null) {
  modelPackageLoading.value = true
  error.value = ''
  try {
    if (artifact) await api.activateModelArtifact(artifact.id)
    else await api.activateBaseModel()
    uieMode.value = 'on_demand'
    localStorage.setItem('uieMode', 'on_demand')
    await Promise.all([refreshModelArtifacts(), refreshModelRuntime()])
  } catch (e) {
    error.value = e.message
  } finally {
    modelPackageLoading.value = false
  }
}

async function removeModelPackage(artifact) {
  if (!window.confirm(`确认删除模型“${artifact.name} ${artifact.version}”吗？\n权重文件会从本机同步删除。`)) return
  modelPackageLoading.value = true
  error.value = ''
  try {
    await api.deleteModelArtifact(artifact.id)
    await refreshModelArtifacts()
  } catch (e) {
    error.value = e.message
  } finally {
    modelPackageLoading.value = false
  }
}

async function refreshTrainingDocuments() {
  try {
    const data = await api.listTrainingDocuments()
    trainingDocuments.value = data.documents || []
  } catch (e) {
    error.value = e.message
  }
}

function startEditLabel(label) {
  editingLabelId.value = label.id
  editingLabel.value = { text: label.text, category: label.category }
}

async function addLabel() {
  if (!labelForm.value.text.trim()) return
  labelLoading.value = true
  error.value = ''
  try {
    await api.createLabel(labelForm.value)
    labelForm.value = { text: '', category: 'person' }
    await Promise.all([refreshLabels(), refreshData()])
  } catch (e) {
    error.value = e.message
  } finally {
    labelLoading.value = false
  }
}

async function saveLabel(labelId) {
  labelLoading.value = true
  error.value = ''
  try {
    await api.updateLabel(labelId, editingLabel.value)
    editingLabelId.value = ''
    await Promise.all([refreshLabels(), refreshData()])
  } catch (e) {
    error.value = e.message
  } finally {
    labelLoading.value = false
  }
}

async function removeLabel(label) {
  if (!window.confirm(`确认停用识别标签“${label.text}”吗？\n历史训练记录仍会保留。`)) return
  labelLoading.value = true
  error.value = ''
  try {
    await api.deleteLabel(label.id)
    await Promise.all([refreshLabels(), refreshData()])
  } catch (e) {
    error.value = e.message
  } finally {
    labelLoading.value = false
  }
}

async function submitAnonymize() {
  if (!anonymizeFile.value) {
    error.value = '请先选择要脱敏的文件。'
    return
  }
  loading.value = true
  error.value = ''
  result.value = null
  reviewOpen.value = false
  const sourceName = anonymizeFile.value.name
  const startedAt = Date.now() - 5000
  processingProgress.value = { percent: 0, detail: '正在上传文件，请稍候…' }
  const progressTimer = window.setInterval(async () => {
    try {
      const latestTasks = await api.listTasks()
      const activeTask = latestTasks.find(task => (
        task.status === 'processing'
        && task.original_name === sourceName
        && new Date(task.created_at).getTime() >= startedAt
      ))
      if (activeTask?.processing_progress) {
        processingProgress.value = activeTask.processing_progress
        tasks.value = latestTasks
      }
    } catch {
      // 主上传请求会返回真正的错误；轮询失败不覆盖它。
    }
  }, 1500)
  try {
    result.value = await api.anonymize(anonymizeFile.value, selectedCategories.value, customEntities.value, uieMode.value)
    await Promise.all([refreshData(), refreshModelRuntime(), refreshLabels()])
    if (result.value?.status === 'review') await openReview(result.value)
  } catch (e) {
    error.value = e.message
    if (e.data?.id) result.value = e.data
  } finally {
    window.clearInterval(progressTimer)
    loading.value = false
    processingProgress.value = null
  }
}

async function submitRestore() {
  if (!selectedTaskId.value || !restoreFile.value) {
    error.value = '请选择原脱敏任务，并上传 AI 处理后的文件。'
    return
  }
  loading.value = true
  error.value = ''
  result.value = null
  try {
    result.value = await api.restore(selectedTaskId.value, restoreFile.value)
    await refreshData()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function deleteTask(task) {
  const confirmed = window.confirm(`确认删除任务“${task.task_name}”吗？\n\n原始文件、脱敏文件、反匿名上传稿、正式文件及匿名映射都会同步删除，且无法恢复。`)
  if (!confirmed) return
  deletingTaskId.value = task.id
  error.value = ''
  try {
    await api.deleteTask(task.id)
    if (selectedTaskId.value === task.id) selectedTaskId.value = ''
    if (result.value?.id === task.id) result.value = null
    await refreshData()
  } catch (e) {
    error.value = e.message
  } finally {
    deletingTaskId.value = ''
  }
}

async function openReview(task = result.value) {
  if (!task?.id) return
  nav.value = 'workspace'
  mode.value = 'anonymize'
  result.value = task
  reviewOpen.value = true
  reviewLoading.value = true
  reviewAdditions.value = ''
  reviewSelectedTokens.value = []
  reviewCategories.value = {}
  reviewAliasChoices.value = {}
  reviewQuery.value = ''
  reviewCategoryFilter.value = 'all'
  reviewSelection.value = ''
  reviewSelectionLocation.value = ''
  error.value = ''
  try {
    reviewData.value = await api.getTaskReview(task.id)
    reviewSelectedTokens.value = reviewData.value.entities.map(entity => entity.key)
    reviewCategories.value = Object.fromEntries(
      reviewData.value.entities.map(entity => [entity.key, entity.category])
    )
    reviewAliasChoices.value = Object.fromEntries(
      (reviewData.value.alias_groups || []).map(group => [group.id, {
        accepted: Boolean(group.accepted),
        canonical: group.canonical
      }])
    )
  } catch (e) {
    error.value = e.message
    reviewOpen.value = false
  } finally {
    reviewLoading.value = false
  }
}

async function applyReview() {
  if (!result.value?.id) return
  reviewLoading.value = true
  error.value = ''
  try {
    reviewData.value = await api.applyTaskReview(
      result.value.id,
      reviewAdditions.value,
      reviewData.value.entities
        .filter(entity => reviewSelectedTokens.value.includes(entity.key))
        .map(entity => ({
          token: entity.token,
          text: entity.text,
          category: reviewCategories.value[entity.key] || entity.category
        })),
      (reviewData.value.alias_groups || []).map(group => ({
        ...group,
        accepted: Boolean(reviewAliasChoices.value[group.id]?.accepted),
        canonical: reviewAliasChoices.value[group.id]?.canonical || group.canonical
      }))
    )
    result.value = reviewData.value.task
    reviewAdditions.value = ''
    reviewSelectedTokens.value = reviewData.value.entities.map(entity => entity.key)
    reviewCategories.value = Object.fromEntries(
      reviewData.value.entities.map(entity => [entity.key, entity.category])
    )
    reviewAliasChoices.value = Object.fromEntries(
      (reviewData.value.alias_groups || []).map(group => [group.id, {
        accepted: Boolean(group.accepted),
        canonical: group.canonical
      }])
    )
    await Promise.all([refreshData(), refreshLabels()])
  } catch (e) {
    error.value = e.message
  } finally {
    reviewLoading.value = false
  }
}

function selectAllReviewCandidates() {
  reviewSelectedTokens.value = reviewData.value.entities.map(entity => entity.key)
}

function clearReviewCandidates() {
  reviewSelectedTokens.value = []
}

function reviewSourceLabel(entity) {
  if (entity.source === 'model') {
    return entity.probability ? `模型 ${(entity.probability * 100).toFixed(0)}%` : '模型候选'
  }
  if (entity.source === 'label') return '本地标签'
  if (entity.source === 'alias') return '简称候选'
  return '规则识别'
}

function categoryInputPrefix(category) {
  const label = labelCategoryOptions.find(item => item.key === category)?.label || '敏感项'
  return label.split(' / ')[0]
    .replace('人员姓名', '人名')
    .replace('联系电话', '电话')
    .replace('证件号码', '证件')
    .replace('电子邮箱', '邮箱')
    .replace('地址信息', '地址')
    .replace('其他敏感项', '敏感项')
}

function captureReviewSelection(payload) {
  const selected = String(payload?.text || '').trim()
  if (selected.length >= 2 && selected.length <= 200) {
    reviewSelection.value = selected
    reviewSelectionLocation.value = payload?.location || '全文预览'
  }
}

function addReviewSelection() {
  if (!reviewSelection.value) return
  const line = `${categoryInputPrefix(reviewSelectionCategory.value)}|${reviewSelection.value}`
  const existing = reviewAdditions.value.split(/\r?\n/).map(item => item.trim()).filter(Boolean)
  if (!existing.some(item => item.toLocaleLowerCase('zh-CN') === line.toLocaleLowerCase('zh-CN'))) {
    reviewAdditions.value = [...existing, line].join('\n')
  }
  reviewSelection.value = ''
  reviewSelectionLocation.value = ''
  window.getSelection()?.removeAllRanges()
}

function fileFromTrainingEvent(event) {
  const file = event.target.files?.[0] || event.dataTransfer?.files?.[0] || null
  if (file && file.size > maxUploadSizeMb.value * 1024 * 1024) {
    trainingDocumentFile.value = null
    if (event.target && 'value' in event.target) event.target.value = ''
    error.value = `训练文档不能超过 ${maxUploadSizeMb.value} MB，当前文件为 ${formatBytes(file.size)}。`
    return
  }
  trainingDocumentFile.value = file
  error.value = ''
}

function initializeTrainingSelection(document) {
  activeTrainingDocument.value = document
  const savedEntities = document.annotations?.entities || []
  const savedKeys = new Set(savedEntities.map(entity => `${entity.text}::${entity.category}`))
  trainingSelectedKeys.value = (document.entities || [])
    .filter(entity => !savedEntities.length || savedKeys.has(`${entity.text}::${entity.category}`))
    .map(entity => entity.key)
  trainingCategories.value = Object.fromEntries(
    (document.entities || []).map(entity => [entity.key, entity.category])
  )
  const machineTexts = new Set((document.entities || []).map(entity => entity.text))
  const labels = Object.fromEntries(labelCategoryOptions.map(item => [item.key, item.label.split(' / ')[0]]))
  trainingAdditions.value = savedEntities
    .filter(entity => !machineTexts.has(entity.text))
    .map(entity => `${labels[entity.category] || '敏感项'}|${entity.text}`)
    .join('\n')
  trainingSelection.value = ''
}

async function uploadTrainingDocument() {
  if (!trainingDocumentFile.value) return
  trainingDocumentLoading.value = true
  error.value = ''
  try {
    const document = await api.uploadTrainingDocument(trainingDocumentFile.value)
    initializeTrainingSelection(document)
    trainingDocumentFile.value = null
    await refreshTrainingDocuments()
  } catch (e) {
    error.value = e.message
  } finally {
    trainingDocumentLoading.value = false
  }
}

async function openTrainingDocument(documentId) {
  trainingDocumentLoading.value = true
  error.value = ''
  try {
    initializeTrainingSelection(await api.getTrainingDocument(documentId))
  } catch (e) {
    error.value = e.message
  } finally {
    trainingDocumentLoading.value = false
  }
}

function captureTrainingSelection(payload) {
  const selected = String(payload?.text || '').trim()
  if (selected.length >= 2 && selected.length <= 200) trainingSelection.value = selected
}

function addTrainingSelection() {
  if (!trainingSelection.value) return
  const prefix = categoryInputPrefix(trainingSelectionCategory.value)
  trainingAdditions.value = `${trainingAdditions.value}${trainingAdditions.value ? '\n' : ''}${prefix}|${trainingSelection.value}`
  trainingSelection.value = ''
  window.getSelection()?.removeAllRanges()
}

async function saveTrainingAnnotations() {
  if (!activeTrainingDocument.value?.id) return
  trainingDocumentLoading.value = true
  error.value = ''
  try {
    const document = await api.saveTrainingAnnotations(
      activeTrainingDocument.value.id,
      trainingAdditions.value,
      (activeTrainingDocument.value.entities || [])
        .filter(entity => trainingSelectedKeys.value.includes(entity.key))
        .map(entity => ({ text: entity.text, category: trainingCategories.value[entity.key] || entity.category })),
      activeTrainingDocument.value.alias_groups || []
    )
    initializeTrainingSelection(document)
    await Promise.all([refreshTrainingDocuments(), refreshLabels(), refreshData()])
  } catch (e) {
    error.value = e.message
  } finally {
    trainingDocumentLoading.value = false
  }
}

async function removeTrainingDocument(document) {
  if (!window.confirm(`确认删除训练文档“${document.original_name}”及其原始文件吗？\n已形成的加密训练样本和本地标签将保留。`)) return
  trainingDocumentLoading.value = true
  try {
    await api.deleteTrainingDocument(document.id)
    if (activeTrainingDocument.value?.id === document.id) activeTrainingDocument.value = null
    await refreshTrainingDocuments()
  } catch (e) {
    error.value = e.message
  } finally {
    trainingDocumentLoading.value = false
  }
}

function openDownload(url) {
  if (url) window.location.assign(url)
}

function selectMode(nextMode) {
  mode.value = nextMode
  nav.value = 'workspace'
  result.value = null
  reviewOpen.value = false
  error.value = ''
}

onMounted(() => Promise.all([refreshData(), refreshModelRuntime(), refreshModelArtifacts(), refreshLabels(), refreshTrainingDocuments()]))
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-mark"><AppIcon name="shield-check" :size="27" /></span>
        <span><strong>隐数盾</strong><small>数据安全平台</small></span>
      </div>

      <div class="side-label">工作空间</div>
      <nav class="side-nav">
        <button title="数据处理台" :class="{ active: nav === 'workspace' }" @click="nav = 'workspace'">
          <span class="nav-icon"><AppIcon name="layout" /></span><span class="nav-text">处理台</span>
        </button>
        <button title="处理记录" :class="{ active: nav === 'history' }" @click="nav = 'history'; refreshData()">
          <span class="nav-icon"><AppIcon name="history" /></span><span class="nav-text">记录</span>
          <span v-if="tasks.length" class="nav-count">{{ tasks.length }}</span>
        </button>
        <button title="质量洞察" :class="{ active: nav === 'analytics' }" @click="nav = 'analytics'; refreshData()">
          <span class="nav-icon"><AppIcon name="chart" /></span><span class="nav-text">洞察</span>
        </button>
        <button title="模型中心" :class="{ active: nav === 'models' }" @click="nav = 'models'; refreshModelArtifacts(); refreshModelRuntime()">
          <span class="nav-icon"><AppIcon name="package" /></span><span class="nav-text">模型</span>
          <span v-if="modelArtifacts.length" class="nav-count">{{ modelArtifacts.length }}</span>
        </button>
        <button title="训练标注" :class="{ active: nav === 'labels' }" @click="nav = 'labels'; refreshLabels(); refreshTrainingDocuments()">
          <span class="nav-icon"><AppIcon name="scan" /></span><span class="nav-text">训练</span>
          <span v-if="trainingLabels.length" class="nav-count">{{ trainingLabels.length }}</span>
        </button>
        <button title="使用说明" :class="{ active: nav === 'guide' }" @click="nav = 'guide'">
          <span class="nav-icon"><AppIcon name="book" /></span><span class="nav-text">指南</span>
        </button>
      </nav>

      <div class="sidebar-note">
        <span class="note-icon"><AppIcon name="file-lock" :size="19" /></span>
        <div><strong>数据仅在本地处理</strong><small>映射关系加密存储，不离开内网环境</small></div>
      </div>
      <div class="sidebar-footer"><span class="online-dot"></span> 本地服务运行中 <small>v1.0</small></div>
    </aside>

    <main class="main-panel">
      <header class="topbar">
        <div>
          <h1>{{ pageMeta[0] }}</h1>
          <p>{{ pageMeta[1] }}</p>
        </div>
        <div class="platform-badge"><span class="status-orbit"><i></i></span><AppIcon name="shield-check" :size="19" /><span><strong>数据安全平台</strong><small>本地服务已连接</small></span></div>
      </header>

      <div class="content-area">
        <div v-if="error" class="alert app-alert global-alert" role="alert">
          <AppIcon name="alert" :size="18" /> <span>{{ error }}</span>
          <button type="button" aria-label="关闭提示" @click="error = ''">×</button>
        </div>
        <template v-if="nav === 'workspace'">
          <section class="stats-grid">
            <article><span class="metric-icon mint"><AppIcon name="file-lock" :size="25" /></span><div><span>累计任务</span><strong>{{ stats.tasks }}</strong><small>文件</small></div><i class="metric-wave"></i></article>
            <article><span class="metric-icon blue"><AppIcon name="scan" :size="25" /></span><div><span>敏感信息</span><strong>{{ stats.entity_occurrences ?? stats.entities }}</strong><small>处</small></div><i class="metric-wave"></i></article>
            <article><span class="metric-icon gold"><AppIcon name="restore" :size="25" /></span><div><span>正式输出</span><strong>{{ stats.restored }}</strong><small>文件</small></div><i class="metric-wave"></i></article>
          </section>

          <section class="process-path" aria-label="数据处理流程">
            <div class="active"><span><AppIcon name="upload" :size="22" /></span><strong>上传</strong></div><i></i>
            <div><span><AppIcon name="scan" :size="22" /></span><strong>识别</strong></div><i></i>
            <div><span><AppIcon name="check" :size="22" /></span><strong>复核</strong></div><i></i>
            <div><span><AppIcon name="download" :size="22" /></span><strong>输出</strong></div>
          </section>

          <div class="mode-switch">
            <button :class="{ active: mode === 'anonymize' }" @click="selectMode('anonymize')">
              <span class="switch-icon"><AppIcon name="file-lock" :size="27" /></span>
              <span><strong>数据匿名</strong><small>发现并隐藏敏感信息</small></span><b>开始</b>
            </button>
            <button :class="{ active: mode === 'restore' }" @click="selectMode('restore')">
              <span class="switch-icon"><AppIcon name="restore" :size="27" /></span>
              <span><strong>数据反匿名</strong><small>恢复匿名信息并正式输出</small></span><b>恢复</b>
            </button>
          </div>

          <section v-if="mode === 'anonymize'" class="work-card">
            <div class="card-heading">
              <span class="step-number"><AppIcon name="upload" :size="23" /></span>
              <div><small class="heading-kicker">STEP 01</small><h2>上传待脱敏文件</h2><p>选择文件，系统自动提取并高亮敏感信息</p></div>
            </div>

            <label
              class="drop-zone"
              :class="{ dragging: dragging === 'anonymize', selected: anonymizeFile }"
              @dragover.prevent="dragging = 'anonymize'"
              @dragleave.prevent="dragging = ''"
              @drop.prevent="fileFromEvent($event, 'anonymize')"
            >
              <input type="file" accept=".xls,.docx,.pdf,.ofd,.txt" @change="fileFromEvent($event, 'anonymize')" />
              <span class="upload-circle"><AppIcon :name="anonymizeFile ? 'check' : 'upload'" :size="25" /></span>
              <template v-if="anonymizeFile">
                <strong>{{ anonymizeFile.name }}</strong>
                <p>{{ formatBytes(anonymizeFile.size) }} · 点击可重新选择</p>
              </template>
              <template v-else>
                <strong>拖放文件到这里，或 <em>点击选择</em></strong>
                <p>支持 XLS、DOCX、PDF、OFD、TXT，单文件不超过 {{ maxUploadSizeMb }} MB</p>
              </template>
            </label>

            <div class="settings-grid">
              <div>
                <label class="form-label app-label">识别类型</label>
                <div class="category-grid">
                  <label v-for="category in categoryOptions" :key="category.key" class="category-check">
                    <input v-model="selectedCategories" type="checkbox" :value="category.key" />
                    <span><i><AppIcon :name="category.icon" :size="21" /></i><b>{{ category.label }}</b><em><AppIcon name="check" :size="15" /></em></span>
                  </label>
                </div>
              </div>
              <div>
                <label class="form-label app-label" for="customEntities">指定敏感词 <small>可选</small></label>
                <textarea id="customEntities" v-model="customEntities" class="form-control" rows="4" placeholder="每行一个，如：中国烟草总公司&#10;也可写：单位|某某卷烟厂"></textarea>
                <div class="form-hint">指定词优先识别，可使用“单位、产品、产区、人名|内容”标注类型。新增内容会加密保存到本机训练标签库，并立即用于后续任务。</div>
              </div>
            </div>

            <div class="uie-settings">
              <div class="uie-heading">
                <span class="uie-icon"><AppIcon name="sparkle" :size="24" /></span>
                <div><strong>智能识别引擎</strong><small>规则 + UIE-base + 本地 OCR</small></div>
                <span class="model-state" :class="{ loaded: modelRuntime.resident_loaded, unavailable: !modelRuntime.available }">
                  {{ !modelRuntime.available ? '模型服务不可用' : modelRuntime.resident_loaded ? '模型已常驻' : '模型未占用内存' }}
                </span>
              </div>
              <div class="uie-mode-grid">
                <label :class="{ active: uieMode === 'on_demand' }">
                  <input type="radio" name="uieMode" value="on_demand" :checked="uieMode === 'on_demand'" :disabled="modelModeLoading" @change="selectUieMode('on_demand')" />
                  <AppIcon name="sparkle" :size="22" /><span><b>临时调用 <em>推荐</em></b><small>节省内存 · 单次加载</small></span>
                </label>
                <label :class="{ active: uieMode === 'resident' }">
                  <input type="radio" name="uieMode" value="resident" :checked="uieMode === 'resident'" :disabled="modelModeLoading" @change="selectUieMode('resident')" />
                  <AppIcon name="database" :size="22" /><span><b>模型常驻</b><small>响应更快 · 占用 2～4 GB</small></span>
                </label>
              </div>
              <div v-if="modelModeLoading" class="model-loading"><span class="spinner-border spinner-border-sm"></span> 正在切换模型运行方式，请稍候…</div>
            </div>

            <div class="action-row">
              <div class="privacy-tip"><AppIcon name="shield-check" :size="18" /> 映射表使用独立密钥加密保存</div>
              <button class="btn primary-btn" :disabled="loading || !anonymizeFile" @click="submitAnonymize">
                <span v-if="loading" class="spinner-border spinner-border-sm"></span>
                <AppIcon v-else name="file-lock" :size="18" />
                {{ loading ? (processingProgress?.stage === 'pdf_ocr' ? '正在本地 OCR…' : '正在识别并生成…') : '开始数据匿名' }}
              </button>
            </div>
            <div v-if="loading && processingProgress" class="task-progress">
              <div><span>{{ processingProgress.detail }}</span><strong>{{ processingProgress.percent || 0 }}%</strong></div>
              <div class="task-progress-track"><i :style="{ width: `${processingProgress.percent || 0}%` }"></i></div>
              <small v-if="processingProgress.ocr_page_count">扫描 PDF：正在逐页本地 OCR，共 {{ processingProgress.ocr_page_count }} 页需要识别</small>
            </div>
          </section>

          <section v-else class="work-card">
            <div class="card-heading">
              <span class="step-number amber"><AppIcon name="restore" :size="23" /></span>
              <div><small class="heading-kicker">RESTORE</small><h2>恢复正式文件</h2><p>关联原任务并上传处理稿，安全恢复正式信息</p></div>
            </div>

            <div class="restore-layout">
              <div>
                <label class="form-label app-label" for="taskSelect">关联原脱敏任务</label>
                <select id="taskSelect" v-model="selectedTaskId" class="form-select">
                  <option value="" disabled>请选择原脱敏任务</option>
                  <option v-for="task in completedTasks" :key="task.id" :value="task.id">{{ task.code }} · {{ task.task_name }}</option>
                </select>
                <div v-if="selectedTask" class="mapping-card">
                  <span><AppIcon name="shield-check" :size="18" /></span>
                  <div><strong>映射已就绪</strong><small>{{ Object.values(selectedTask.entity_counts || {}).reduce((a, b) => a + b, 0) }} 个敏感项 · {{ formatDate(selectedTask.created_at) }}</small></div>
                </div>
              </div>
              <label
                class="drop-zone compact"
                :class="{ dragging: dragging === 'restore', selected: restoreFile }"
                @dragover.prevent="dragging = 'restore'"
                @dragleave.prevent="dragging = ''"
                @drop.prevent="fileFromEvent($event, 'restore')"
              >
                <input type="file" accept=".xls,.docx,.pdf,.ofd,.txt" @change="fileFromEvent($event, 'restore')" />
                <span class="upload-circle amber"><AppIcon :name="restoreFile ? 'check' : 'upload'" :size="23" /></span>
                <div><strong>{{ restoreFile?.name || '上传 AI 处理后的文件' }}</strong><p>{{ restoreFile ? formatBytes(restoreFile.size) : `点击选择或拖放到这里，最大 ${maxUploadSizeMb} MB` }}</p></div>
              </label>
            </div>

            <div class="notice-box"><AppIcon name="alert" :size="18" /><span>匿名代码带有本机命名标识，例如 <code>【{{ selectedTask?.anonymization_namespace || '本机标识' }}-单001】</code>。请勿拆分或改写；恢复还必须使用本机加密映射。</span></div>
            <div class="action-row justify-content-end">
              <button class="btn restore-btn" :disabled="loading || !selectedTaskId || !restoreFile" @click="submitRestore">
                <span v-if="loading" class="spinner-border spinner-border-sm"></span>
                <AppIcon v-else name="restore" :size="18" />
                {{ loading ? '正在恢复…' : '生成正式文件' }}
              </button>
            </div>
          </section>

          <section v-if="result && !result.error_message" class="result-card">
            <span class="result-check"><AppIcon :name="result.status === 'review' ? 'info' : 'check'" :size="25" /></span>
            <div class="result-main">
              <h3>{{ result.status === 'review' ? '候选识别完成，请人工确认' : result.status === 'restored' ? '正式文件已生成' : '文件脱敏完成' }}</h3>
              <p>{{ result.code }} · {{ result.task_name }}</p>
              <div v-if="result.status !== 'restored'" class="entity-tags">
                <span v-if="result.anonymization_namespace">本机标识 {{ result.anonymization_namespace }}</span>
                <span v-for="(count, label) in result.entity_counts" :key="label">{{ label }} {{ count }}</span>
                <span v-if="result.uie_detected_count">UIE 补充 {{ result.uie_detected_count }}</span>
                <span v-if="result.uie_rejected_count">已过滤低置信/冲突 {{ result.uie_rejected_count }}</span>
                <span v-if="result.ocr_page_count">本地 OCR {{ result.ocr_page_count }} 页</span>
                <span v-if="result.recognition_mode === 'on_demand'">临时调用</span>
                <span v-else-if="result.recognition_mode === 'resident'">模型常驻</span>
                <span v-if="!Object.keys(result.entity_counts || {}).length">未发现自动识别项，请确认文件不是扫描图片，或补充“指定敏感词”</span>
              </div>
            </div>
            <div class="result-actions">
              <button v-if="result.status === 'review' || result.anonymized_download_url" class="btn light-btn" @click="openReview(result)">
                <AppIcon name="info" :size="18" /> {{ result.status === 'review' ? '人工确认' : '重新校正' }}
              </button>
              <button v-if="result.restored_download_url || result.anonymized_download_url" class="btn download-btn" @click="openDownload(result.status === 'restored' ? result.restored_download_url : result.anonymized_download_url)">
                <AppIcon name="download" :size="18" /> 下载文件
              </button>
            </div>
          </section>

          <section v-if="reviewOpen" class="review-card">
            <div class="review-heading">
              <div><h3>{{ result?.status === 'review' ? '人工确认敏感信息' : '重新校正识别结果' }}</h3><p>高亮查看候选项所在原文；保留需要脱敏的数据、取消误识别、修改类型，并补录漏识别内容。</p></div>
              <button class="review-close" @click="reviewOpen = false">关闭</button>
            </div>
            <div v-if="reviewLoading" class="review-loading"><span class="spinner-border spinner-border-sm"></span> 正在读取或重新处理文件…</div>
            <template v-else>
              <div class="review-warning">{{ result?.status === 'review' ? '尚未开放脱敏文件下载。只有确认过的候选项和人工补录项会进入脱敏结果。' : '重新校正会生成新版脱敏文件，同时保留旧匿名编号的恢复能力；已有反匿名上传稿和正式输出会清除，请重新生成。' }}</div>
              <div class="review-workbench">
                <section class="review-preview-pane">
                  <div class="pane-heading">
                    <span><AppIcon name="scan" :size="21" /></span>
                    <div><strong>全文原文预览</strong><small>从左侧任意位置划选漏识别字段，再到右侧点击箭头加入</small></div>
                    <b>{{ reviewData.preview?.length || 0 }} 个分段</b>
                  </div>
                  <DocumentPreview
                    class="review-document-preview"
                    :sections="reviewData.preview"
                    :entities="reviewData.entities"
                    :selected-keys="reviewSelectedTokens"
                    title="上传文件全文预览"
                    subtitle="彩色高亮为机器候选；灰色删除线表示已取消脱敏"
                    empty-text="未提取到可预览文字；扫描 PDF 请确认 OCR 已成功完成。"
                    @text-selected="captureReviewSelection"
                  />
                </section>
                <aside class="review-control-pane">
                  <section class="selection-transfer" :class="{ ready: reviewSelection }">
                    <div class="selection-transfer-icon"><AppIcon name="arrow-right" :size="27" /></div>
                    <div class="selection-copy">
                      <small>{{ reviewSelection ? `选自 ${reviewSelectionLocation}` : '在左侧文档中按住鼠标划选文字' }}</small>
                      <strong>{{ reviewSelection || '划词后可补充机器漏识别项' }}</strong>
                    </div>
                    <select v-model="reviewSelectionCategory" class="form-select" :disabled="!reviewSelection">
                      <option v-for="category in labelCategoryOptions" :key="category.key" :value="category.key">{{ category.label }}</option>
                    </select>
                    <button class="selection-arrow" :disabled="!reviewSelection" title="把所选文字加入识别项" @click="addReviewSelection">
                      <AppIcon name="arrow-right" :size="24" /><span>加入识别</span>
                    </button>
                  </section>

                  <section class="candidate-pane">
                    <div class="review-list-heading">
                      <label class="form-label app-label">识别候选 <small>勾选表示确认需要脱敏</small></label>
                      <span><button @click="selectAllReviewCandidates">全选</button><button @click="clearReviewCandidates">清空</button></span>
                    </div>
                    <div class="review-filters">
                      <label class="search-field"><AppIcon name="search" :size="17" /><input v-model="reviewQuery" class="form-control" placeholder="搜索字段或匿名代码" /></label>
                      <select v-model="reviewCategoryFilter" class="form-select">
                        <option value="all">全部类型</option>
                        <option v-for="category in labelCategoryOptions" :key="category.key" :value="category.key">{{ category.label }}</option>
                      </select>
                      <span>{{ filteredReviewEntities.length }} 项</span>
                    </div>
                    <div class="review-entities">
                      <article v-for="entity in filteredReviewEntities" :key="entity.key" :class="{ selected: reviewSelectedTokens.includes(entity.key), rejected: !reviewSelectedTokens.includes(entity.key) }">
                        <div class="review-entity-main">
                          <input v-model="reviewSelectedTokens" type="checkbox" :value="entity.key" :aria-label="`选择 ${entity.text}`" />
                          <span class="review-token">{{ entity.token }}</span>
                          <strong>{{ entity.text }}</strong>
                          <span class="review-source">{{ reviewSourceLabel(entity) }} · {{ entity.occurrence_count || 0 }} 处</span>
                          <select v-model="reviewCategories[entity.key]" class="form-select review-category" :disabled="!reviewSelectedTokens.includes(entity.key)">
                            <option v-for="category in labelCategoryOptions" :key="category.key" :value="category.key">{{ category.label }}</option>
                          </select>
                        </div>
                        <div v-if="entity.occurrences?.length" class="review-contexts">
                          <p v-for="(occurrence, occurrenceIndex) in entity.occurrences" :key="occurrenceIndex">
                            <small>{{ occurrence.location }}</small>
                            <span>{{ occurrence.prefix }}</span><mark>{{ occurrence.match }}</mark><span>{{ occurrence.suffix }}</span>
                          </p>
                        </div>
                      </article>
                      <p v-if="!filteredReviewEntities.length" class="review-empty">没有符合当前筛选条件的候选项。可从左侧原文划词补录。</p>
                    </div>
                  </section>

                  <section class="manual-additions">
                    <label class="form-label app-label">人工补充清单 <small>{{ reviewAdditions.split(/\r?\n/).filter(Boolean).length }} 项</small></label>
                    <textarea v-model="reviewAdditions" class="form-control review-textarea" placeholder="可在左侧划词加入，也可手动输入：&#10;单位|山东中烟&#10;产品|文山雨露&#10;人名|张三"></textarea>
                    <p class="form-hint">确认字段会加密保存为本机标签；误识别会保存为否决样本。模型包导出不会包含这些原文数据。</p>
                  </section>
                </aside>
              </div>
              <section v-if="reviewData.alias_groups?.length" class="alias-review">
                <div class="preview-toolbar"><div><strong>可能指代同一单位</strong><small>请人工判断；合并后共用一个匿名代码，反匿名统一恢复为所选标准名称</small></div></div>
                <article v-for="group in reviewData.alias_groups" :key="group.id">
                  <label><input v-model="reviewAliasChoices[group.id].accepted" type="checkbox" /> 确认属于同一实体</label>
                  <div class="alias-members"><span v-for="member in group.members" :key="member">{{ member }}</span></div>
                  <label>反匿名标准名称
                    <select v-model="reviewAliasChoices[group.id].canonical" class="form-select" :disabled="!reviewAliasChoices[group.id].accepted">
                      <option v-for="member in group.members" :key="member" :value="member">{{ member }}</option>
                    </select>
                  </label>
                  <small>{{ group.reason }} · 建议置信度 {{ Math.round((group.confidence || 0) * 100) }}%</small>
                </article>
              </section>
              <div class="review-footer">
                <span>已选择 {{ reviewSelectedTokens.length }} / {{ reviewData.entities?.length || 0 }} 项 · 历史已排除 {{ reviewData.excluded_count || 0 }} 项</span>
                <button class="btn primary-btn" :disabled="reviewLoading || (!reviewAdditions.trim() && !reviewSelectedTokens.length)" @click="applyReview">
                  <AppIcon name="check" :size="18" /> {{ result?.status === 'review' ? '确认选择并生成脱敏文件' : '保存校正并重新脱敏' }}
                </button>
              </div>
            </template>
          </section>

          <div class="format-note"><strong>格式说明：</strong>DOCX 仅改写命中的文本区间并保留原有文字节点和样式；XLS、TXT、OFD 尽量保持原结构。扫描 PDF 会自动在本机逐页 OCR，PDF 输出仍会重新排版。</div>
        </template>

        <template v-else-if="nav === 'history'">
          <section class="history-card">
            <div class="history-toolbar">
              <div><h2>全部处理记录</h2><p>每条记录保存原始上传、脱敏输出、反匿名上传和正式输出；删除记录将同步删除文件</p></div>
              <button class="btn light-btn" :disabled="loadingHistory" @click="refreshData"><AppIcon name="history" :size="17" /> 刷新</button>
            </div>
            <div class="table-responsive">
              <table class="table align-middle mb-0">
                <thead><tr><th>任务 / 文件</th><th>格式</th><th>敏感项</th><th>状态</th><th>处理时间</th><th class="text-end">操作</th></tr></thead>
                <tbody>
                  <tr v-for="task in tasks" :key="task.id">
                    <td><strong>{{ task.task_name }}</strong><small>{{ task.code }} · {{ task.display_name || task.original_name }} · {{ formatBytes(task.file_size) }}</small></td>
                    <td><span class="file-type">{{ task.file_type.toUpperCase() }}</span></td>
                    <td>{{ Object.values(task.entity_counts || {}).reduce((a, b) => a + b, 0) }} 项</td>
                    <td>
                      <span class="status-pill" :class="statusMeta(task.status)[1]"><i></i>{{ statusMeta(task.status)[0] }}</span>
                      <small v-if="task.status === 'processing' && task.processing_progress?.detail" class="history-progress">
                        {{ task.processing_progress.percent || 0 }}% · {{ task.processing_progress.detail }}
                      </small>
                    </td>
                    <td>{{ formatDate(task.created_at) }}</td>
                    <td class="text-end table-actions">
                      <button v-if="task.anonymized_download_url" title="下载脱敏文件" @click="openDownload(task.anonymized_download_url)"><AppIcon name="download" :size="17" /></button>
                      <button v-if="task.status === 'review' || task.anonymized_download_url" :title="task.status === 'review' ? '人工确认识别结果' : '校正识别结果'" @click="openReview(task)"><AppIcon name="info" :size="17" /></button>
                      <button v-if="task.restored_download_url" class="amber" title="下载正式文件" @click="openDownload(task.restored_download_url)"><AppIcon name="restore" :size="17" /></button>
                      <button class="danger" title="删除记录及所有文件" :disabled="deletingTaskId === task.id" @click="deleteTask(task)">
                        <span v-if="deletingTaskId === task.id" class="spinner-border spinner-border-sm"></span>
                        <AppIcon v-else name="trash" :size="17" />
                      </button>
                    </td>
                  </tr>
                  <tr v-if="!tasks.length"><td colspan="6" class="empty-state">暂无处理记录，请先在数据处理台上传文件。</td></tr>
                </tbody>
              </table>
            </div>
          </section>
        </template>

        <template v-else-if="nav === 'analytics'">
          <AnalyticsPanel :stats="stats" :loading="loadingHistory" @refresh="refreshData" />
        </template>

        <template v-else-if="nav === 'models'">
          <section class="model-hero">
            <span class="model-hero-icon"><AppIcon name="package" :size="31" /></span>
            <div>
              <small class="heading-kicker">LOCAL MODEL REGISTRY</small>
              <h2>本地模型中心</h2>
              <p>管理 UIE 权重版本、受控导入与可移植导出。权重始终保存在本机 Docker 数据卷中。</p>
            </div>
            <div class="active-model-summary">
              <small>当前识别模型</small>
              <strong>{{ modelArtifacts.find(item => item.is_active)?.name || modelBase.name }}</strong>
              <span :class="{ online: modelRuntime.available }"><i></i>{{ modelRuntime.available ? (modelRuntime.resident_loaded ? '已加载到内存' : '服务就绪') : '服务不可用' }}</span>
            </div>
          </section>

          <div class="model-center-grid">
            <section class="model-import-card">
              <div class="section-title-row">
                <span><AppIcon name="upload" :size="23" /></span>
                <div><h2>导入训练权重</h2><p>接受经本平台或 PaddleNLP 微调后打包的 ZIP 检查点</p></div>
              </div>
              <label class="model-drop" :class="{ selected: modelPackageFile }">
                <input type="file" accept=".zip,application/zip" @change="fileFromModelPackageEvent" />
                <AppIcon :name="modelPackageFile ? 'check' : 'package'" :size="31" />
                <strong>{{ modelPackageFile?.name || '选择 UIE 模型包' }}</strong>
                <small>{{ modelPackageFile ? `${formatBytes(modelPackageFile.size)} · 等待安全校验` : `ZIP 格式 · 最大 ${modelPackageMaxMb} MB` }}</small>
              </label>
              <div class="model-meta-fields">
                <label><span>显示名称</span><input v-model="modelPackageForm.name" class="form-control" maxlength="120" placeholder="例如：行业实体识别模型" /></label>
                <label><span>版本</span><input v-model="modelPackageForm.version" class="form-control" maxlength="64" placeholder="例如：1.2.0" /></label>
              </div>
              <button class="btn primary-btn model-import-action" :disabled="modelPackageLoading || !modelPackageFile" @click="importModelPackage">
                <span v-if="modelPackageLoading" class="spinner-border spinner-border-sm"></span><AppIcon v-else name="upload" :size="18" />
                校验并导入模型
              </button>
            </section>

            <aside class="model-safety-card">
              <div class="section-title-row">
                <span><AppIcon name="shield-check" :size="23" /></span>
                <div><h2>安全边界</h2><p>模型能共享，业务数据不随模型导出</p></div>
              </div>
              <ul>
                <li><AppIcon name="check" :size="17" /><span><strong>结构校验</strong><small>必须包含权重、配置和分词器词表</small></span></li>
                <li><AppIcon name="check" :size="17" /><span><strong>归档防护</strong><small>拦截路径穿越、符号链接和异常压缩比</small></span></li>
                <li><AppIcon name="check" :size="17" /><span><strong>隐私隔离</strong><small>不导出原文、标签库、匿名映射和部署密钥</small></span></li>
                <li><AppIcon name="check" :size="17" /><span><strong>完整性清单</strong><small>逐文件生成 SHA-256，可核对模型版本</small></span></li>
              </ul>
            </aside>
          </div>

          <section class="model-registry-card">
            <div class="registry-heading">
              <div><h2>模型版本</h2><p>激活会先释放常驻模型，新权重在下一次识别时加载；业务规则与本机标签仍会叠加生效。</p></div>
              <span>{{ modelArtifacts.length + 1 }} 个版本</span>
            </div>
            <div class="model-registry-list">
              <article :class="{ active: modelBase.is_active }">
                <span class="registry-icon"><AppIcon name="model" :size="25" /></span>
                <div class="registry-main"><strong>{{ modelBase.name }}</strong><small>内置基础模型 · 随系统镜像提供</small></div>
                <span class="registry-status">{{ modelBase.is_active ? '当前使用' : '可切换' }}</span>
                <div class="registry-actions"><button v-if="!modelBase.is_active" class="btn light-btn" :disabled="modelPackageLoading" @click="activateModelPackage()">设为当前</button></div>
              </article>
              <article v-for="artifact in modelArtifacts" :key="artifact.id" :class="{ active: artifact.is_active }">
                <span class="registry-icon custom"><AppIcon name="package" :size="25" /></span>
                <div class="registry-main">
                  <strong>{{ artifact.name }} <em>v{{ artifact.version }}</em></strong>
                  <small>{{ artifact.base_model }} · {{ formatBytes(artifact.package_size) }} · {{ artifact.file_count }} 个文件 · {{ artifact.package_sha256.slice(0, 12) }}</small>
                </div>
                <span class="registry-status">{{ artifact.is_active ? '当前使用' : formatDate(artifact.created_at) }}</span>
                <div class="registry-actions">
                  <button v-if="!artifact.is_active" class="btn light-btn" :disabled="modelPackageLoading" @click="activateModelPackage(artifact)">设为当前</button>
                  <a class="btn icon-btn" :href="api.modelArtifactExportUrl(artifact.id)" title="导出可移植模型包"><AppIcon name="download" :size="18" /></a>
                  <button class="btn icon-btn danger" title="删除本机模型包" :disabled="modelPackageLoading || artifact.is_active" @click="removeModelPackage(artifact)"><AppIcon name="trash" :size="18" /></button>
                </div>
              </article>
            </div>
          </section>
        </template>

        <template v-else-if="nav === 'labels'">
          <section class="training-explain">
            <span><AppIcon name="info" :size="25" /></span>
            <div>
              <small class="heading-kicker">HUMAN IN THE LOOP</small><h2>训练标注闭环</h2>
              <p>机器预标 → 人工校正 → 本地训练集</p>
            </div>
            <div class="training-count"><strong>{{ trainingLabels.length }}</strong><small>有效标签</small><strong>{{ trainingExampleCount }}</strong><small>训练样本</small></div>
          </section>

          <section class="annotation-card">
            <div class="annotation-upload">
              <div><h2>上传训练文档</h2><p>支持与脱敏任务相同的格式；原文、预标和人工结果均只在本机保存，敏感内容加密入库</p></div>
              <label class="annotation-file"><input type="file" accept=".xls,.docx,.pdf,.ofd,.txt" @change="fileFromTrainingEvent" /><span>{{ trainingDocumentFile?.name || '选择样本文档' }}</span></label>
              <button class="btn primary-btn" :disabled="trainingDocumentLoading || !trainingDocumentFile" @click="uploadTrainingDocument"><span v-if="trainingDocumentLoading" class="spinner-border spinner-border-sm"></span><AppIcon v-else name="scan" :size="18" /> 机器预标</button>
              <a class="btn light-btn" href="/api/training/export/"><AppIcon name="download" :size="18" /> 导出训练集</a>
            </div>
            <div v-if="trainingDocuments.length" class="training-documents">
              <article v-for="document in trainingDocuments" :key="document.id" :class="{ active: activeTrainingDocument?.id === document.id }">
                <button class="training-doc-main" @click="openTrainingDocument(document.id)"><strong>{{ document.original_name }}</strong><small>{{ document.status_label }} · {{ document.annotation_count }} 条标注 · {{ formatDate(document.updated_at) }}</small></button>
                <button class="training-doc-delete" title="删除训练文档" @click="removeTrainingDocument(document)">×</button>
              </article>
            </div>

            <div v-if="activeTrainingDocument" class="annotation-workbench">
              <div class="annotation-heading"><div><h3>{{ activeTrainingDocument.original_name }}</h3><p>彩色文本是机器候选；取消勾选可否决，类别可修改，也可在原文中划词补标</p></div><span>{{ trainingSelectedKeys.length }} / {{ activeTrainingDocument.entities?.length || 0 }} 个机器候选</span></div>
              <div class="annotation-layout">
                <DocumentPreview
                  class="training-preview"
                  :sections="activeTrainingDocument.preview"
                  :entities="activeTrainingDocument.entities"
                  :selected-keys="trainingSelectedKeys"
                  :show-toolbar="false"
                  @text-selected="captureTrainingSelection"
                />
                <aside class="annotation-panel">
                  <div v-if="trainingSelection" class="selection-add">
                    <small>已选择原文</small><strong>{{ trainingSelection }}</strong>
                    <select v-model="trainingSelectionCategory" class="form-select"><option v-for="category in labelCategoryOptions" :key="category.key" :value="category.key">{{ category.label }}</option></select>
                    <button class="btn light-btn" @click="addTrainingSelection">加入人工标注</button>
                  </div>
                  <div class="annotation-candidates">
                    <label v-for="entity in activeTrainingDocument.entities" :key="entity.key" :class="{ rejected: !trainingSelectedKeys.includes(entity.key) }">
                      <input v-model="trainingSelectedKeys" type="checkbox" :value="entity.key" />
                      <strong>{{ entity.text }}</strong>
                      <select v-model="trainingCategories[entity.key]" class="form-select"><option v-for="category in labelCategoryOptions" :key="category.key" :value="category.key">{{ category.label }}</option></select>
                    </label>
                  </div>
                  <label class="form-label app-label">人工补标 <small>每行一个，也可在左侧划词添加</small></label>
                  <textarea v-model="trainingAdditions" class="form-control" placeholder="单位|陆良厂&#10;人名|张三"></textarea>
                  <button class="btn primary-btn annotation-save" :disabled="trainingDocumentLoading || (!trainingSelectedKeys.length && !trainingAdditions.trim())" @click="saveTrainingAnnotations">保存标注并立即学习</button>
                  <p class="form-hint">“立即学习”指本地精确词库立即生效；UIE-base 权重不会因一份文档自动重训。达到足够样本后用导出的 JSONL 集中微调，可避免小样本灾难性遗忘。</p>
                </aside>
              </div>
            </div>
          </section>

          <section class="label-card">
            <div class="label-add-row">
              <div><h2>新增识别标签</h2><p>适合补充内部人员、简称、车间、供应商和项目代号</p></div>
              <select v-model="labelForm.category" class="form-select">
                <option v-for="category in labelCategoryOptions" :key="category.key" :value="category.key">{{ category.label }}</option>
              </select>
              <input v-model="labelForm.text" class="form-control" maxlength="200" placeholder="输入需要识别的完整内容" @keyup.enter="addLabel" />
              <button class="btn primary-btn" :disabled="labelLoading || !labelForm.text.trim()" @click="addLabel">保存标签</button>
            </div>

            <div class="table-responsive">
              <table class="table align-middle mb-0 label-table">
                <thead><tr><th>类型</th><th>标签内容</th><th>更新时间</th><th class="text-end">操作</th></tr></thead>
                <tbody>
                  <tr v-for="label in trainingLabels" :key="label.id">
                    <template v-if="editingLabelId === label.id">
                      <td><select v-model="editingLabel.category" class="form-select"><option v-for="category in labelCategoryOptions" :key="category.key" :value="category.key">{{ category.label }}</option></select></td>
                      <td><input v-model="editingLabel.text" class="form-control" maxlength="200" /></td>
                      <td>{{ formatDate(label.updated_at) }}</td>
                      <td class="text-end label-actions"><button class="save" :disabled="labelLoading" @click="saveLabel(label.id)">保存</button><button @click="editingLabelId = ''">取消</button></td>
                    </template>
                    <template v-else>
                      <td><span class="file-type">{{ label.category_label }}</span></td>
                      <td><strong>{{ label.text }}</strong></td>
                      <td>{{ formatDate(label.updated_at) }}</td>
                      <td class="text-end label-actions"><button @click="startEditLabel(label)">修改</button><button class="danger" :disabled="labelLoading" @click="removeLabel(label)">停用</button></td>
                    </template>
                  </tr>
                  <tr v-if="!trainingLabels.length"><td colspan="4" class="empty-state">暂无本地训练标签；也可以在脱敏页面的“指定敏感词”中添加。</td></tr>
                </tbody>
              </table>
            </div>
          </section>
        </template>

        <template v-else>
          <section class="guide-hero">
            <span><AppIcon name="shield-check" :size="34" /></span>
            <div><small class="heading-kicker">SECURE WORKFLOW</small><h2>安全可逆的三步流程</h2><p>原文不出本机，映射加密保存。</p></div>
          </section>
          <section class="guide-grid">
            <article><b>1</b><AppIcon name="file-lock" :size="27" /><h3>本地匿名</h3><p>上传原始文件，系统识别单位、人名、证件等信息，替换为稳定匿名标记。</p></article>
            <article><b>2</b><AppIcon name="info" :size="27" /><h3>AI 内容处理</h3><p>下载脱敏文件交由 AI 做校对、总结或改写，期间保留所有匿名标记。</p></article>
            <article><b>3</b><AppIcon name="restore" :size="27" /><h3>安全恢复</h3><p>选择原任务并上传 AI 处理稿，系统在本地恢复敏感信息并输出正式文件。</p></article>
          </section>
          <section class="guide-details">
            <h3>使用建议</h3>
            <ul>
              <li>自动识别前，可在“指定敏感词”中补充业务单位、部门、供应商和人员名单。</li>
              <li>“临时调用”在 OCR 子进程退出后加载 UIE-base，并在任务结束后释放约 2～4 GB 内存；“模型常驻”建议至少 32 GB 系统内存。</li>
              <li>人工确认的每个字段都会加密保存并立即加入本地词库，同时形成后续批量微调所需的训练样本。</li>
              <li>匿名代码包含由本机映射密钥派生的安装标识；校正任务会保留历史匿名编号，旧脱敏稿仍可关联原任务恢复。</li>
              <li>扫描 PDF 会自动调用 PP-StructureV3 精简 OCR，并显示渲染、模型加载、当前页和百分比；PDF 处理结果会重新排版，复杂公文建议优先使用 DOCX。</li>
              <li>生产部署时必须修改环境文件中的 Django 密钥、映射加密密钥和数据库密码。</li>
              <li>AI 处理过程中不得删除、拆分或改写全角书名号包裹的匿名标记。</li>
            </ul>
          </section>
        </template>
      </div>
    </main>
  </div>
</template>
