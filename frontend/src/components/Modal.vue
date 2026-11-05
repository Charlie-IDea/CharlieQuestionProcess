<script setup lang="ts">
import { onMounted,onUnmounted,ref } from 'vue'
import { X } from 'lucide-vue-next'
defineProps<{title:string;wide?:boolean}>()
const emit=defineEmits(['close'])
const dialog=ref<HTMLElement>()
const close=(e:KeyboardEvent)=>{if(e.key==='Escape') emit('close')}
onMounted(()=>{document.addEventListener('keydown',close);dialog.value?.focus()})
onUnmounted(()=>document.removeEventListener('keydown',close))
</script>
<template><div class="modal-backdrop" @click.self="emit('close')"><section ref="dialog" tabindex="-1" role="dialog" aria-modal="true" :aria-label="title" class="modal" :class="{wide}"><header><h2>{{title}}</h2><button class="icon-button" aria-label="关闭" @click="emit('close')"><X :size="20"/></button></header><slot/></section></div></template>
