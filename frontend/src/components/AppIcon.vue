<script setup>
defineProps({
  name: { type: String, required: true },
  size: { type: [Number, String], default: 20 },
  strokeWidth: { type: [Number, String], default: 2 }
})
</script>

<template>
  <svg
    xmlns="http://www.w3.org/2000/svg"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-linecap="round"
    stroke-linejoin="round"
    :stroke-width="strokeWidth"
    aria-hidden="true"
  >
    <template v-if="name === 'shield-check'">
      <path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" />
      <path d="m9 12 2 2 4-4" />
    </template>
    <template v-else-if="name === 'file-lock'">
      <path d="M4 9.8V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.7.7l3.6 3.6A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2h-3" />
      <path d="M14 2v5a1 1 0 0 0 1 1h5M9 17v-2a2 2 0 0 0-4 0v2" />
      <rect width="8" height="5" x="3" y="17" rx="1" />
    </template>
    <template v-else-if="name === 'history'">
      <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
      <path d="M3 3v5h5m4-1v5l4 2" />
    </template>
    <template v-else-if="name === 'building'">
      <path d="M10 12h4m-4-4h4m0 13v-3a2 2 0 0 0-4 0v3" />
      <path d="M6 10H4a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-2M6 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16" />
    </template>
    <template v-else-if="name === 'restore'">
      <path d="M12 7v6m0-4h2M3 12a9 9 0 1 0 9-9 9.74 9.74 0 0 0-6.74 2.74L3 8" />
      <path d="M3 3v5h5" /><circle cx="12" cy="15" r="2" />
    </template>
    <template v-else-if="name === 'download'">
      <path d="M12 15V3m9 12v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <path d="m7 10 5 5 5-5" />
    </template>
    <template v-else-if="name === 'upload'">
      <path d="M12 16V4m-5 5 5-5 5 5M20 15v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-4" />
    </template>
    <template v-else-if="name === 'layout'">
      <rect width="18" height="18" x="3" y="3" rx="2" /><path d="M3 9h18M9 21V9" />
    </template>
    <template v-else-if="name === 'chart'">
      <path d="M3 3v18h18" /><path d="m7 16 4-5 3 3 5-7" />
    </template>
    <template v-else-if="name === 'book'">
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V4H6.5A2.5 2.5 0 0 0 4 6.5z" /><path d="M4 6.5v13A2.5 2.5 0 0 0 6.5 22H20" />
    </template>
    <template v-else-if="name === 'check'">
      <path d="m20 6-11 11-5-5" />
    </template>
    <template v-else-if="name === 'alert'">
      <path d="M21.7 18 13.7 4a2 2 0 0 0-3.4 0L2.3 18A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3Z" /><path d="M12 9v4m0 4h.01" />
    </template>
    <template v-else-if="name === 'trash'">
      <path d="M3 6h18M8 6V4h8v2m3 0-1 15H6L5 6m5 5v6m4-6v6" />
    </template>
    <template v-else>
      <circle cx="12" cy="12" r="9" /><path d="M12 8h.01M11 12h1v4h1" />
    </template>
  </svg>
</template>
