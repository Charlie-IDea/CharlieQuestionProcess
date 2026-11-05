import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import Dashboard from './pages/Dashboard.vue'
import Students from './pages/Students.vue'
import Imports from './pages/Imports.vue'
import Questions from './pages/Questions.vue'
import Papers from './pages/Papers.vue'
import Grading from './pages/Grading.vue'
import Mistakes from './pages/Mistakes.vue'
import Settings from './pages/Settings.vue'
import PrintPaper from './pages/PrintPaper.vue'
import './style.css'
import 'katex/dist/katex.min.css'

const router=createRouter({history:createWebHistory(),scrollBehavior:()=>({top:0,left:0}),routes:[
  {path:'/',component:Dashboard,meta:{title:'教学概览',eyebrow:'WORKSPACE'}},
  {path:'/students/:id?',component:Students,meta:{title:'学生档案',eyebrow:'STUDENTS'}},
  {path:'/imports/:id?',component:Imports,meta:{title:'资料录入',eyebrow:'IMPORT CENTER'}},
  {path:'/questions',component:Questions,meta:{title:'我的题库',eyebrow:'QUESTION BANK'}},
  {path:'/papers/:id?',component:Papers,meta:{title:'试卷与练习',eyebrow:'PAPERS & PRACTICE'}},
  {path:'/grading/:id?',component:Grading,meta:{title:'批改工作台',eyebrow:'GRADING STUDIO'}},
  {path:'/mistakes',component:Mistakes,meta:{title:'错题与复练',eyebrow:'LEARNING LOOP'}},
  {path:'/settings',component:Settings,meta:{title:'工作空间设置',eyebrow:'SETTINGS'}},
  {path:'/print/:id',component:PrintPaper,meta:{title:'打印预览'}},
  {path:'/:pathMatch(.*)*',redirect:'/'}
]})
createApp(App).use(router).mount('#app')
