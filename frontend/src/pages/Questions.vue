<script setup lang="ts">
import { computed,onMounted,ref } from 'vue'
import { useRoute } from 'vue-router'
import { Plus,Search,LibraryBig } from 'lucide-vue-next'
import { api,post,kindName } from '../api'
import QuestionEditor from '../components/QuestionEditor.vue'
import EmptyState from '../components/EmptyState.vue'
import Modal from '../components/Modal.vue'
const route=useRoute()
const questions=ref<any[]>([]),search=ref(''),kind=ref(''),status=ref(String(route.query.status||'approved')),tag=ref(''),difficulty=ref(''),error=ref(''),show=ref(false),busy=ref(false)
const form=ref({stem:'',kind:'solution',tags:'',grade:'初三'})
const tags=computed(()=>[...new Set(questions.value.flatMap(q=>q.tags))])
const filtered=computed(()=>questions.value.filter(q=>(!status.value||q.status===status.value)&&(!kind.value||q.kind===kind.value)&&(!tag.value||q.tags.includes(tag.value))&&(!difficulty.value||q.difficulty===Number(difficulty.value))&&(q.stem+q.source+q.tags.join('')).includes(search.value)))
async function load(){try{questions.value=await api('questions/')}catch(e:any){error.value=e.message}}
onMounted(load)
async function create(){busy.value=true;try{await post('questions/',{...form.value,tags:form.value.tags.split(/[、,，]/).filter(Boolean)});status.value='draft';show.value=false;await load()}catch(e:any){error.value=e.message}finally{busy.value=false}}
</script>
<template><div class="page-heading"><div><p class="eyebrow">QUESTION BANK</p><h1>好题，慢慢积累<span class="heading-dot">.</span></h1><p class="subtitle">你的私有题库，也是可持续生长的教学资产。</p></div><div class="inline"><RouterLink to="/imports?new=1" class="button secondary">从资料导入</RouterLink><button class="button primary" @click="show=true"><Plus :size="18"/>添加题目</button></div></div><div v-if="error" class="notice danger">{{error}}</div><div class="toolbar question-filters"><div class="search-field"><Search :size="17"/><input v-model="search" placeholder="搜索题干、来源、知识点" aria-label="搜索题库"/></div><select v-model="status" aria-label="审核状态"><option value="approved">已审核题目</option><option value="draft">待审核题目</option><option value="">全部状态</option></select><select v-model="kind" aria-label="题型"><option value="">全部题型</option><option v-for="(name,key) in kindName" :value="key">{{name}}</option></select><select v-model="tag" aria-label="知识点"><option value="">全部知识点</option><option v-for="t in tags">{{t}}</option></select><select v-model="difficulty" aria-label="难度"><option value="">全部难度</option><option v-for="n in 5" :value="n">难度 {{n}}</option></select></div><p class="muted small results-count">找到 {{filtered.length}} 道题目</p><QuestionEditor v-for="q in filtered" :key="q.id+':'+q.revision" :question="q" @changed="load"/><EmptyState v-if="!filtered.length" title="还没有符合条件的题目" text="调整筛选，或上传试卷逐步建立题库。"/>
 <Modal v-if="show" title="添加题目" @close="show=false"><form @submit.prevent="create"><div v-if="error" class="notice danger">{{error}}</div><label>题干<textarea v-model="form.stem" required rows="6" placeholder="公式可用 $x^2+2x=3$ 表示"/></label><div class="form-grid"><label>题型<select v-model="form.kind"><option v-for="(name,key) in kindName" :value="key">{{name}}</option></select></label><label>年级<input v-model="form.grade"/></label></div><label>知识点（顿号分隔）<input v-model="form.tags"/></label><button class="button primary full" :disabled="busy">保存并继续审核答案</button></form></Modal>
</template>
