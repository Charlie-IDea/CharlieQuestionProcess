<script setup lang="ts">
import { FolderOpen } from 'lucide-vue-next'
defineProps<{title:string;text?:string}>()
</script>
<template><div class="empty"><FolderOpen :size="35" stroke-width="1.25"/><h3>{{title}}</h3><p>{{text}}</p><slot/></div></template>
