<script setup>
import { computed } from 'vue'

const props = defineProps({
  sections: { type: Array, default: () => [] },
  entities: { type: Array, default: () => [] },
  selectedKeys: { type: Array, default: () => [] },
  title: { type: String, default: '' },
  subtitle: { type: String, default: '' },
  emptyText: { type: String, default: '未提取到可预览文字。' },
  showToolbar: { type: Boolean, default: true }
})

defineEmits(['text-selected'])

const entityMap = computed(() => Object.fromEntries(
  props.entities.map(entity => [entity.key, entity])
))
const selectedSet = computed(() => new Set(props.selectedKeys))

function segments(section) {
  const result = []
  let cursor = 0
  for (const span of [...(section.spans || [])].sort((a, b) => a.start - b.start)) {
    if (span.start > cursor) result.push({ text: section.text.slice(cursor, span.start), plain: true })
    const key = `${span.token}::${span.entity_text || span.text}`
    const entity = entityMap.value[key]
    result.push({
      text: section.text.slice(span.start, span.end),
      key,
      category: entity?.category || span.category,
      selected: selectedSet.value.has(key),
      title: `${entity?.category_label || span.category} · ${span.token}`
    })
    cursor = span.end
  }
  if (cursor < section.text.length) result.push({ text: section.text.slice(cursor), plain: true })
  return result
}
</script>

<template>
  <div class="document-preview" @mouseup="$emit('text-selected')">
    <div v-if="showToolbar" class="preview-toolbar">
      <div><strong>{{ title }}</strong><small>{{ subtitle }}</small></div>
      <span>{{ sections.length }} 个文本区块</span>
    </div>
    <div class="preview-pages">
      <section v-for="section in sections" :key="section.index" class="preview-section">
        <header>{{ section.location }}</header>
        <p><template v-for="(segment, index) in segments(section)" :key="index"><span v-if="segment.plain">{{ segment.text }}</span><mark v-else :class="[`entity-${segment.category}`, { rejected: !segment.selected }]" :title="segment.title">{{ segment.text }}</mark></template></p>
      </section>
      <p v-if="!sections.length" class="review-empty">{{ emptyText }}</p>
    </div>
  </div>
</template>
