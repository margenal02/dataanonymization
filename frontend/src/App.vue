<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from './api'
import AppIcon from './components/AppIcon.vue'

const nav = ref('workspace')
const mode = ref('anonymize')
const tasks = ref([])
const stats = ref({ tasks: 0, completed: 0, restored: 0, entities: 0 })
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
const selectedCategories = ref(['organization', 'person', 'phone', 'id_card', 'email', 'address'])

const categoryOptions = [
  { key: 'organization', label: '单位 / 部门' },
  { key: 'person', label: '人员姓名' },
  { key: 'phone', label: '联系电话' },
  { key: 'id_card', label: '证件号码' },
  { key: 'email', label: '电子邮箱' },
  { key: 'address', label: '地址信息' }
]

const completedTasks = computed(() => tasks.value.filter(task => ['completed', 'restored'].includes(task.status)))
const selectedTask = computed(() => tasks.value.find(task => task.id === selectedTaskId.value))

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
    completed: ['脱敏完成', 'status-completed'],
    restored: ['已生成正式版', 'status-restored'],
    failed: ['处理失败', 'status-failed']
  }[status] || [status, '']
}

function fileFromEvent(event, target) {
  const file = event.target.files?.[0] || event.dataTransfer?.files?.[0]
  if (!file) return
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

async function submitAnonymize() {
  if (!anonymizeFile.value) {
    error.value = '请先选择要脱敏的文件。'
    return
  }
  loading.value = true
  error.value = ''
  result.value = null
  try {
    result.value = await api.anonymize(anonymizeFile.value, selectedCategories.value, customEntities.value)
    await refreshData()
  } catch (e) {
    error.value = e.message
    if (e.data?.id) result.value = e.data
  } finally {
    loading.value = false
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

function openDownload(url) {
  if (url) window.location.assign(url)
}

function selectMode(nextMode) {
  mode.value = nextMode
  nav.value = 'workspace'
  result.value = null
  error.value = ''
}

onMounted(refreshData)
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
          <h1>{{ nav === 'workspace' ? '数据处理台' : nav === 'history' ? '处理记录' : '使用说明' }}</h1>
          <p>{{ nav === 'workspace' ? '文件级敏感信息匿名化与安全恢复' : nav === 'history' ? '查看并下载历史处理结果' : '了解安全、可逆的数据处理流程' }}</p>
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
                <p>支持 XLS、DOCX、PDF、OFD、TXT，单文件不超过 50 MB</p>
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
                <div class="form-hint">指定词优先识别，可使用“单位|内容”或“人名|内容”标注类型</div>
              </div>
            </div>

            <div class="action-row">
              <div class="privacy-tip"><AppIcon name="shield-check" :size="18" /> 映射表使用独立密钥加密保存</div>
              <button class="btn primary-btn" :disabled="loading || !anonymizeFile" @click="submitAnonymize">
                <span v-if="loading" class="spinner-border spinner-border-sm"></span>
                <AppIcon v-else name="file-lock" :size="18" />
                {{ loading ? '正在识别并处理…' : '开始数据匿名' }}
              </button>
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
                <div><strong>{{ restoreFile?.name || '上传 AI 处理后的文件' }}</strong><p>{{ restoreFile ? formatBytes(restoreFile.size) : '点击选择或拖放到这里' }}</p></div>
              </label>
            </div>

            <div class="notice-box"><AppIcon name="alert" :size="18" /><span>请勿修改形如 <code>【单位_A1B2_001】</code> 的匿名标记，否则对应信息将无法恢复。</span></div>
            <div class="action-row justify-content-end">
              <button class="btn restore-btn" :disabled="loading || !selectedTaskId || !restoreFile" @click="submitRestore">
                <span v-if="loading" class="spinner-border spinner-border-sm"></span>
                <AppIcon v-else name="restore" :size="18" />
                {{ loading ? '正在恢复…' : '生成正式文件' }}
              </button>
            </div>
          </section>

          <section v-if="result && !result.error_message" class="result-card">
            <span class="result-check"><AppIcon name="check" :size="25" /></span>
            <div class="result-main">
              <h3>{{ result.status === 'restored' ? '正式文件已生成' : '文件脱敏完成' }}</h3>
              <p>{{ result.code }} · {{ result.task_name }}</p>
              <div v-if="result.status !== 'restored'" class="entity-tags">
                <span v-for="(count, label) in result.entity_counts" :key="label">{{ label }} {{ count }}</span>
                <span v-if="!Object.keys(result.entity_counts || {}).length">未发现自动识别项，请确认文件不是扫描图片，或补充“指定敏感词”</span>
              </div>
            </div>
            <button class="btn download-btn" @click="openDownload(result.status === 'restored' ? result.restored_download_url : result.anonymized_download_url)">
              <AppIcon name="download" :size="18" /> 下载文件
            </button>
          </section>

          <div class="format-note"><strong>格式说明：</strong>DOCX、XLS、TXT、OFD 尽量保持原结构；文本型 PDF 将生成排版规范的新 PDF。扫描 PDF 需先完成 OCR。</div>
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
                    <td><span class="status-pill" :class="statusMeta(task.status)[1]"><i></i>{{ statusMeta(task.status)[0] }}</span></td>
                    <td>{{ formatDate(task.created_at) }}</td>
                    <td class="text-end table-actions">
                      <button v-if="task.anonymized_download_url" title="下载脱敏文件" @click="openDownload(task.anonymized_download_url)"><AppIcon name="download" :size="17" /></button>
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
              <li>PDF 扫描件请先 OCR；PDF 处理结果会重新排版，复杂公文建议优先使用 DOCX。</li>
              <li>生产部署时必须修改环境文件中的 Django 密钥、映射加密密钥和数据库密码。</li>
              <li>AI 处理过程中不得删除、拆分或改写全角书名号包裹的匿名标记。</li>
            </ul>
          </section>
        </template>
      </div>
    </main>
  </div>
</template>
