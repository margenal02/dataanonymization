<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from './api'
import AppIcon from './components/AppIcon.vue'

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
const modelRuntime = ref({ enabled: true, available: false, model: 'uie-micro', resident_loaded: false })
const modelModeLoading = ref(false)
const trainingLabels = ref([])
const trainingExampleCount = ref(0)
const labelForm = ref({ text: '', category: 'person' })
const editingLabelId = ref('')
const editingLabel = ref({ text: '', category: 'person' })
const labelLoading = ref(false)
const reviewOpen = ref(false)
const reviewLoading = ref(false)
const reviewData = ref({ entities: [], excluded_count: 0 })
const reviewAdditions = ref('')
const reviewSelectedTokens = ref([])
const reviewCategories = ref({})
const processingProgress = ref(null)
const selectedCategories = ref(['organization', 'person', 'product', 'location', 'phone', 'id_card', 'email', 'address'])

const categoryOptions = [
  { key: 'organization', label: '单位 / 部门' },
  { key: 'person', label: '人员姓名' },
  { key: 'product', label: '品牌 / 产品' },
  { key: 'location', label: '产区 / 地点' },
  { key: 'phone', label: '联系电话' },
  { key: 'id_card', label: '证件号码' },
  { key: 'email', label: '电子邮箱' },
  { key: 'address', label: '地址信息' }
]
const labelCategoryOptions = [...categoryOptions, { key: 'custom', label: '其他敏感项' }]

const completedTasks = computed(() => tasks.value.filter(task => ['completed', 'restored'].includes(task.status)))
const selectedTask = computed(() => tasks.value.find(task => task.id === selectedTaskId.value))
const maxUploadSizeMb = computed(() => Number(stats.value.max_upload_size_mb) || 200)

function formatBytes(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatDate(value) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false
  }).format(new Date(value))
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
    modelRuntime.value = { enabled: true, available: false, model: 'uie-micro', resident_loaded: false, detail: e.message }
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
  error.value = ''
  try {
    reviewData.value = await api.getTaskReview(task.id)
    reviewSelectedTokens.value = reviewData.value.entities.map(entity => entity.token)
    reviewCategories.value = Object.fromEntries(
      reviewData.value.entities.map(entity => [entity.token, entity.category])
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
        .filter(entity => reviewSelectedTokens.value.includes(entity.token))
        .map(entity => ({
          token: entity.token,
          category: reviewCategories.value[entity.token] || entity.category
        }))
    )
    result.value = reviewData.value.task
    reviewAdditions.value = ''
    reviewSelectedTokens.value = reviewData.value.entities.map(entity => entity.token)
    reviewCategories.value = Object.fromEntries(
      reviewData.value.entities.map(entity => [entity.token, entity.category])
    )
    await Promise.all([refreshData(), refreshLabels()])
  } catch (e) {
    error.value = e.message
  } finally {
    reviewLoading.value = false
  }
}

function selectAllReviewCandidates() {
  reviewSelectedTokens.value = reviewData.value.entities.map(entity => entity.token)
}

function clearReviewCandidates() {
  reviewSelectedTokens.value = []
}

function reviewSourceLabel(entity) {
  if (entity.source === 'model') {
    return entity.probability ? `模型 ${(entity.probability * 100).toFixed(0)}%` : '模型候选'
  }
  if (entity.source === 'label') return '本地标签'
  return '规则识别'
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

onMounted(() => Promise.all([refreshData(), refreshModelRuntime(), refreshLabels()]))
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-mark"><AppIcon name="shield-check" :size="27" /></span>
        <span><strong>隐数盾</strong><small>烟草行业数据安全平台</small></span>
      </div>

      <div class="side-label">工作空间</div>
      <nav class="side-nav">
        <button :class="{ active: nav === 'workspace' }" @click="nav = 'workspace'">
          <AppIcon name="layout" /> 数据处理台
        </button>
        <button :class="{ active: nav === 'history' }" @click="nav = 'history'; refreshData()">
          <AppIcon name="history" /> 处理记录
          <span v-if="tasks.length" class="nav-count">{{ tasks.length }}</span>
        </button>
        <button :class="{ active: nav === 'labels' }" @click="nav = 'labels'; refreshLabels()">
          <AppIcon name="info" /> 训练标签
          <span v-if="trainingLabels.length" class="nav-count">{{ trainingLabels.length }}</span>
        </button>
        <button :class="{ active: nav === 'guide' }" @click="nav = 'guide'">
          <AppIcon name="book" /> 使用说明
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
          <h1>{{ nav === 'workspace' ? '数据处理台' : nav === 'history' ? '处理记录' : nav === 'labels' ? '本地训练标签' : '使用说明' }}</h1>
          <p>{{ nav === 'workspace' ? '文件级敏感信息匿名化与安全恢复' : nav === 'history' ? '查看并下载历史处理结果' : nav === 'labels' ? '维护本地词库并沉淀模型训练样本' : '了解安全、可逆的数据处理流程' }}</p>
        </div>
        <div class="industry-badge"><AppIcon name="building" :size="17" /> 烟草行业专用</div>
      </header>

      <div class="content-area">
        <template v-if="nav === 'workspace'">
          <section class="stats-grid">
            <article><span>累计处理</span><strong>{{ stats.tasks }}</strong><small>个文件任务</small></article>
            <article><span>已识别敏感项</span><strong>{{ stats.entities }}</strong><small>处数据替换</small></article>
            <article><span>已生成正式版</span><strong>{{ stats.restored }}</strong><small>个恢复文件</small></article>
          </section>

          <div class="mode-switch">
            <button :class="{ active: mode === 'anonymize' }" @click="selectMode('anonymize')">
              <span class="switch-icon"><AppIcon name="file-lock" /></span>
              <span><strong>数据匿名</strong><small>隐藏单位、人名等敏感信息</small></span>
            </button>
            <button :class="{ active: mode === 'restore' }" @click="selectMode('restore')">
              <span class="switch-icon"><AppIcon name="restore" /></span>
              <span><strong>数据反匿名</strong><small>恢复 AI 处理后的正式文件</small></span>
            </button>
          </div>

          <div v-if="error" class="alert app-alert" role="alert">
            <AppIcon name="alert" :size="18" /> <span>{{ error }}</span>
          </div>

          <section v-if="mode === 'anonymize'" class="work-card">
            <div class="card-heading">
              <span class="step-number">01</span>
              <div><h2>上传待脱敏文件</h2><p>系统将识别文件中的敏感信息并替换为稳定匿名标记</p></div>
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
                    <span><AppIcon name="check" :size="13" /> {{ category.label }}</span>
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
                <div><strong>UIE-micro 智能识别方式</strong><small>规则负责精确匹配，UIE 补充识别人名、单位、产品、产区和地址</small></div>
                <span class="model-state" :class="{ loaded: modelRuntime.resident_loaded, unavailable: !modelRuntime.available }">
                  {{ !modelRuntime.available ? '模型服务不可用' : modelRuntime.resident_loaded ? '模型已常驻' : '模型未占用内存' }}
                </span>
              </div>
              <div class="uie-mode-grid">
                <label :class="{ active: uieMode === 'on_demand' }">
                  <input type="radio" name="uieMode" value="on_demand" :checked="uieMode === 'on_demand'" :disabled="modelModeLoading" @change="selectUieMode('on_demand')" />
                  <span><b>临时调用（推荐）</b><small>每个文件加载一次，处理后立即释放约 0.9～1.5 GB 内存；每次会增加冷启动等待时间。</small></span>
                </label>
                <label :class="{ active: uieMode === 'resident' }">
                  <input type="radio" name="uieMode" value="resident" :checked="uieMode === 'resident'" :disabled="modelModeLoading" @change="selectUieMode('resident')" />
                  <span><b>模型常驻</b><small>首次加载后保留在内存，后续文件更快；空闲时仍持续占用约 0.9～1.5 GB 内存。</small></span>
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
              <span class="step-number amber">02</span>
              <div><h2>恢复正式文件</h2><p>使用原任务的加密映射，将 AI 处理稿中的匿名标记恢复为正式信息</p></div>
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

            <div class="notice-box"><AppIcon name="alert" :size="18" /><span>请勿修改形如 <code>【单001】</code>、<code>【人001】</code> 的匿名标记，否则对应信息将无法恢复。</span></div>
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
              <div class="review-warning">{{ result?.status === 'review' ? '尚未开放脱敏文件下载。只有确认过的候选项和人工补录项会进入脱敏结果。' : '重新校正会更新匿名映射；已有反匿名上传稿和正式文件将作废。' }}</div>
              <div class="review-grid">
                <div>
                  <div class="review-list-heading">
                    <label class="form-label app-label">识别候选 <small>勾选表示确认需要脱敏</small></label>
                    <span><button @click="selectAllReviewCandidates">全选</button><button @click="clearReviewCandidates">清空</button></span>
                  </div>
                  <div class="review-entities">
                    <article v-for="entity in reviewData.entities" :key="entity.token" :class="{ selected: reviewSelectedTokens.includes(entity.token), rejected: !reviewSelectedTokens.includes(entity.token) }">
                      <div class="review-entity-main">
                        <input v-model="reviewSelectedTokens" type="checkbox" :value="entity.token" :aria-label="`选择 ${entity.text}`" />
                        <span class="review-token">{{ entity.token }}</span>
                        <strong>{{ entity.text }}</strong>
                        <span class="review-source">{{ reviewSourceLabel(entity) }}</span>
                        <select v-model="reviewCategories[entity.token]" class="form-select review-category" :disabled="!reviewSelectedTokens.includes(entity.token)">
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
                    <p v-if="!reviewData.entities?.length" class="review-empty">当前没有识别项，请在右侧补充漏识别内容。</p>
                  </div>
                </div>
                <div>
                  <label class="form-label app-label">补充漏识别内容 <small>每行一个</small></label>
                  <textarea v-model="reviewAdditions" class="form-control review-textarea" placeholder="单位|山东中烟&#10;产品|文山雨露&#10;产区|文山&#10;人名|张三"></textarea>
                  <p class="form-hint">补录内容会立即加入加密本地词库；勾掉的误识别会保存为加密否决样本，供后续微调评测。</p>
                </div>
              </div>
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

        <template v-else-if="nav === 'labels'">
          <section class="training-explain">
            <span><AppIcon name="info" :size="25" /></span>
            <div>
              <h2>标签立即用于识别，修改历史沉淀为训练数据</h2>
              <p>新增或修改标签后，系统会加密保存原值并立即加入本地精确词库；同时保留一条加密训练样本，供后续集中微调 UIE-micro。保存训练数据不等于每次立即重新训练模型，避免频繁训练造成卡顿和模型退化。</p>
            </div>
            <div class="training-count"><strong>{{ trainingLabels.length }}</strong><small>有效标签</small><strong>{{ trainingExampleCount }}</strong><small>训练样本</small></div>
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
            <div><h2>安全可逆的三步处理流程</h2><p>敏感原文不进入外部 AI 服务，正式信息只在本地恢复。</p></div>
          </section>
          <section class="guide-grid">
            <article><b>1</b><AppIcon name="file-lock" :size="27" /><h3>本地匿名</h3><p>上传原始文件，系统识别单位、人名、证件等信息，替换为稳定匿名标记。</p></article>
            <article><b>2</b><AppIcon name="info" :size="27" /><h3>AI 内容处理</h3><p>下载脱敏文件交由 AI 做校对、总结或改写，期间保留所有匿名标记。</p></article>
            <article><b>3</b><AppIcon name="restore" :size="27" /><h3>安全恢复</h3><p>选择原任务并上传 AI 处理稿，系统在本地恢复敏感信息并输出正式文件。</p></article>
          </section>
          <section class="guide-details">
            <h3>使用建议</h3>
            <ul>
              <li>自动识别前，建议在“指定敏感词”中补充烟草专卖局、卷烟厂、供应商和人员名单。</li>
              <li>“临时调用”在每个任务结束后释放 UIE 内存；“模型常驻”适合连续处理大量文件，但空闲时仍占用约 0.9～1.5 GB 内存。</li>
              <li>新增或修改的识别标签会加密保存并立即加入本地词库，同时形成后续批量微调所需的训练样本。</li>
              <li>扫描 PDF 会自动调用容器内简体中文+英文 OCR，并显示当前页和百分比；PDF 处理结果会重新排版，复杂公文建议优先使用 DOCX。</li>
              <li>生产部署时必须修改环境文件中的 Django 密钥、映射加密密钥和数据库密码。</li>
              <li>AI 处理过程中不得删除、拆分或改写全角书名号包裹的匿名标记。</li>
            </ul>
          </section>
        </template>
      </div>
    </main>
  </div>
</template>
