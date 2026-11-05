<script setup lang="ts">
import { ref } from 'vue'
const props=defineProps<{region:any}>()
const emit=defineEmits(['update'])
const start=ref<number[]|null>(null),current=ref<number[]|null>(null)
function point(e:PointerEvent){const r=(e.currentTarget as HTMLElement).getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))]}
function down(e:PointerEvent){start.value=point(e);current.value=start.value;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)}
function move(e:PointerEvent){if(start.value)current.value=point(e)}
function up(){if(start.value&&current.value){const [x,y]=start.value,[a,b]=current.value;if(Math.abs(a-x)>.015&&Math.abs(b-y)>.015)emit('update',{...props.region,bbox:[Math.min(x,a),Math.min(y,b),Math.max(x,a),Math.max(y,b)]})}start.value=null;current.value=null}
function style(){const b=start.value&&current.value?[Math.min(start.value[0],current.value[0]),Math.min(start.value[1],current.value[1]),Math.max(start.value[0],current.value[0]),Math.max(start.value[1],current.value[1])]:props.region.bbox;return {left:b[0]*100+'%',top:b[1]*100+'%',width:(b[2]-b[0])*100+'%',height:(b[3]-b[1])*100+'%'}}
</script>
<template><div class="crop-wrap"><p class="helper">在原始页面上拖动，调整本题范围</p><div class="crop-stage" @pointerdown="down" @pointermove="move" @pointerup="up" @pointercancel="up"><img :src="`/api/pages/${region.page}/image/`" alt="原始页面，拖动调整题目裁切范围" draggable="false"/><div class="crop-selection" :style="style()"></div></div></div></template>
