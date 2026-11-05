<script setup lang="ts">
import { ref,onMounted } from 'vue'
import { useRoute,useRouter } from 'vue-router'
import { ArrowLeft,ArrowUpRight,ClipboardCheck } from 'lucide-vue-next'
import { api } from '../api'
import AttemptCard from '../components/AttemptCard.vue'
import EmptyState from '../components/EmptyState.vue'
const route=useRoute(),router=useRouter(),submissions=ref<any[]>([]),submission=ref<any>(null),error=ref('')
async function load(){try{if(route.params.id)submission.value=await api(`submissions/${route.params.id}/`);else submissions.value=await api('submissions/')}catch(e:any){error.value=e.message}}
onMounted(load)
function count(s:any){return s.attempts.filter((a:any)=>a.final_score!==null).length}
</script>
<template><div class="page-heading"><div><RouterLink v-if="submission" to="/grading" class="back-link"><ArrowLeft :size="15"/>批改工作台</RouterLink><p v-else class="eyebrow">GRADING STUDIO</p><h1>{{submission?submission.paper_title:'把反馈，落到每一道题'}}<span class="heading-dot">.</span></h1><p class="subtitle">{{submission?submission.student_name+' · '+submission.test_date:'规则辅助客观题，AI建议解答题，最终判断由你掌握。'}}</p></div><RouterLink v-if="!submission" to="/imports?new=1" class="button primary">录入学生作答<ArrowUpRight :size="17"/></RouterLink><RouterLink v-else :to="'/students/'+submission.student" class="button secondary">查看学生档案</RouterLink></div><div v-if="error" class="notice danger">{{error}}</div>
 <template v-if="!submission"><section class="panel"><div v-if="submissions.length" class="table-scroll"><table><thead><tr><th>作业 / 测试</th><th>学生</th><th>日期</th><th>批改进度</th><th></th></tr></thead><tbody><tr v-for="s in submissions" @click="router.push('/grading/'+s.id)"><td><strong>{{s.paper_title}}</strong><span v-if="s.is_fragment" class="tag">零散错题</span></td><td>{{s.student_name}}</td><td>{{s.test_date}}</td><td><span class="status" :class="count(s)===s.attempts.length?'committed':'review'">{{count(s)}} / {{s.attempts.length}} 已定分</span></td><td><ArrowUpRight :size="17"/></td></tr></tbody></table></div><EmptyState v-else title="等待第一份学生作答" text="上传学生卷并审核归档，或从已发布试卷建立作答记录。"/></section></template>
 <template v-else><div class="notice neutral"><ClipboardCheck :size="20"/><div><strong>{{count(submission)}} / {{submission.attempts.length}} 道题已定分</strong><p>{{submission.is_fragment?'这是零散错题记录，不推算整卷总分。':'请先核对作答识别，再确认评分。失分题将自动进入学生错题档案。'}}</p></div></div><AttemptCard v-for="a in submission.attempts" :key="a.id+':'+a.revision" :attempt="a" @changed="load"/></template>
</template>
