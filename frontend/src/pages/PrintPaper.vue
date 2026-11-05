<script setup lang="ts">
import { onMounted,ref } from 'vue'
import { useRoute } from 'vue-router'
import { Printer,ArrowLeft } from 'lucide-vue-next'
import { api } from '../api'
import MathText from '../components/MathText.vue'
const route=useRoute(),paper=ref<any>(null),error=ref(''),answers=ref(false)
onMounted(async()=>{try{paper.value=await api(`papers/${route.params.id}/`);if(paper.value.status!=='published')error.value='请先发布试卷后打印。'}catch(e:any){error.value=e.message}})
function print(){window.print()}
</script>
<template><div class="print-toolbar"><RouterLink :to="'/papers/'+route.params.id" class="button secondary"><ArrowLeft :size="16"/>返回试卷</RouterLink><label class="check-row"><input v-model="answers" type="checkbox"/>答案解析版</label><button class="button primary" :disabled="!!error" @click="print"><Printer :size="17"/>打印 / 保存为 PDF</button></div><div v-if="error" class="notice danger">{{error}}</div><article v-else-if="paper" class="print-paper"><header><p>知序 · {{answers?'参考答案与解析':'数学专项练习'}}</p><h1>{{paper.title}}</h1><div v-if="!answers" class="print-identity">姓名：________________　日期：________________</div></header><div v-for="item in paper.items" :key="item.id" class="print-question"><div><strong>{{item.label}}.</strong> <MathText :text="item.snapshot.stem"/> <small>（{{item.max_score}} 分）</small></div><div class="options-grid"><MathText v-for="option in item.snapshot.options" :text="option"/></div><img v-for="r in item.snapshot.figure_regions||[]" class="print-figure" :src="`/api/pages/${r.page}/image/?bbox=${r.bbox.join(',')}`" alt="试题配图"/><div v-if="answers" class="print-answer"><strong>参考答案：</strong><MathText :text="item.snapshot.answer"/><p><MathText :text="item.snapshot.explanation"/></p><p><MathText :text="item.snapshot.rubric"/></p></div><div v-else-if="['solution','proof'].includes(item.snapshot.kind)" class="answer-space"></div><div v-else class="short-answer-space"></div></div></article></template>
