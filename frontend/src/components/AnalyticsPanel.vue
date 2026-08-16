<script setup>
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  stats: { type: Object, required: true },
  loading: { type: Boolean, default: false }
})
defineEmits(['refresh'])

const review = computed(() => props.stats.review_quality || {})
const performance = computed(() => props.stats.performance || {})

function maxCount(items) {
  return Math.max(1, ...(items || []).map(item => Number(item.count) || 0))
}

function width(item, items) {
  return `${Math.max(item.count ? 4 : 0, (Number(item.count) || 0) * 100 / maxCount(items))}%`
}

function statusClass(key) {
  return `insight-${key}`
}
</script>

<template>
  <section class="analytics-hero">
    <div>
      <span class="eyebrow">LOCAL QUALITY OBSERVATORY</span>
      <h2>识别质量与数据运营</h2>
      <p>所有指标由本地任务和人工复核记录聚合，不上传文档原文或敏感字段。</p>
    </div>
    <button class="btn light-btn" :disabled="loading" @click="$emit('refresh')">
      <span v-if="loading" class="spinner-border spinner-border-sm"></span>
      <AppIcon v-else name="history" :size="17" /> 刷新指标
    </button>
  </section>

  <section class="analytics-kpis">
    <article><i class="kpi-visual green"><AppIcon name="check" :size="24" /></i><div><small>任务完成率</small><strong>{{ stats.completion_rate || 0 }}%</strong><span>{{ stats.completed || 0 }} / {{ stats.tasks || 0 }} 个任务</span></div></article>
    <article><i class="kpi-visual blue"><AppIcon name="scan" :size="24" /></i><div><small>候选采纳率</small><strong>{{ review.candidate_acceptance_rate || 0 }}%</strong><span>人工采纳 {{ review.selected_count || 0 }} 项</span></div></article>
    <article><i class="kpi-visual gold"><AppIcon name="sparkle" :size="24" /></i><div><small>人工补漏</small><strong>{{ review.manual_added_count || 0 }}</strong><span>召回优化线索</span></div></article>
    <article><i class="kpi-visual violet"><AppIcon name="history" :size="24" /></i><div><small>平均识别耗时</small><strong>{{ performance.average_recognition_seconds || 0 }}s</strong><span>{{ performance.measured_tasks || 0 }} 个样本</span></div></article>
  </section>

  <div class="analytics-grid">
    <section class="analytics-card">
      <header><div><h3>任务状态</h3><p>当前任务池的交付与异常结构</p></div><span>{{ stats.tasks || 0 }} 总计</span></header>
      <div class="status-composition">
        <span v-for="item in stats.status_distribution || []" :key="item.key" :class="statusClass(item.key)" :style="{ width: `${stats.tasks ? item.count * 100 / stats.tasks : 0}%` }"></span>
      </div>
      <div class="distribution-list compact-list">
        <div v-for="item in stats.status_distribution || []" :key="item.key"><i :class="statusClass(item.key)"></i><span>{{ item.label }}</span><strong>{{ item.count }}</strong></div>
      </div>
    </section>

    <section class="analytics-card">
      <header><div><h3>人工复核闭环</h3><p>采纳、否决、改类和实体合并均可审计</p></div><span>{{ review.reviewed_tasks || 0 }} 次复核</span></header>
      <div class="quality-grid">
        <div><span>机器候选</span><strong>{{ review.candidate_count || 0 }}</strong></div>
        <div><span>人工否决</span><strong>{{ review.rejected_count || 0 }}</strong></div>
        <div><span>类别修正</span><strong>{{ review.category_corrected_count || 0 }}</strong></div>
        <div><span>同实体合并</span><strong>{{ review.alias_accepted_count || 0 }}</strong></div>
      </div>
      <p class="metric-note">候选采纳率反映模型精确度趋势，人工补漏量反映召回短板；它们不是经过独立金标准集计算的正式 Precision / Recall。</p>
    </section>

    <section class="analytics-card">
      <header><div><h3>敏感信息分布</h3><p>按已确认唯一字段统计，用于确定词库与微调优先级</p></div><span>{{ stats.entities || 0 }} 个字段</span></header>
      <div class="bar-list">
        <div v-for="item in stats.entity_distribution || []" :key="item.label">
          <span>{{ item.label }}</span><div><i :style="{ width: width(item, stats.entity_distribution) }"></i></div><strong>{{ item.count }}</strong>
        </div>
        <p v-if="!stats.entity_distribution?.length" class="analytics-empty">完成任务后将显示类别分布。</p>
      </div>
    </section>

    <section class="analytics-card">
      <header><div><h3>文件格式结构</h3><p>评估 OCR 与格式保真工作的投入方向</p></div></header>
      <div class="bar-list file-bars">
        <div v-for="item in stats.file_type_distribution || []" :key="item.label">
          <span>{{ item.label }}</span><div><i :style="{ width: width(item, stats.file_type_distribution) }"></i></div><strong>{{ item.count }}</strong>
        </div>
        <p v-if="!stats.file_type_distribution?.length" class="analytics-empty">暂无文件任务。</p>
      </div>
    </section>
  </div>

  <section class="analytics-card analytics-governance">
    <div><AppIcon name="shield-check" :size="24" /></div>
    <div><h3>指标口径与治理边界</h3><p>统计仅包含任务状态、类别计数、耗时和人工动作计数；不在分析接口中返回原始敏感文本。训练样本仍使用独立密钥加密，导出 JSONL 时才在本机流式解密。</p></div>
    <dl><div><dt>活跃标签</dt><dd>{{ stats.active_labels || 0 }}</dd></div><div><dt>训练样本</dt><dd>{{ stats.training_examples || 0 }}</dd></div><div><dt>待复核</dt><dd>{{ stats.pending_review || 0 }}</dd></div><div><dt>失败任务</dt><dd>{{ stats.failed || 0 }}</dd></div></dl>
  </section>
</template>
