<script setup lang="ts">
import { computed,onMounted,ref } from 'vue'
import { useRoute,useRouter } from 'vue-router'
import { LayoutDashboard, Users, ScanLine, LibraryBig, Files, ClipboardCheck, Repeat2, Settings, Menu, X, LogOut, ArrowUpRight, Sprout, ShieldCheck, ChevronDown } from 'lucide-vue-next'
import { api,post,session,loadSession } from './api'
const route=useRoute(),router=useRouter()
const error=ref(''),busy=ref(false),mobile=ref(false),authMode=ref('login')
const form=ref({name:'',email:'',password:''})
const message=ref('')
const nav=[{to:'/',title:'教学概览',icon:LayoutDashboard},{to:'/students',title:'学生档案',icon:Users},
 {to:'/imports',title:'资料录入',icon:ScanLine},{to:'/questions',title:'我的题库',icon:LibraryBig},
 {to:'/papers',title:'试卷与练习',icon:Files},{to:'/grading',title:'批改工作台',icon:ClipboardCheck},{to:'/mistakes',title:'错题与复练',icon:Repeat2}]
const printMode=computed(()=>route.path.startsWith('/print/'))
onMounted(async()=>{try{await loadSession();const params=new URLSearchParams(location.search)
 if(params.get('verify')){const data=await post('auth/verify/',{token:params.get('verify')});message.value=data.message;history.replaceState({},'','/')}
 if(params.get('reset')) authMode.value='reset'
 }catch(e:any){error.value=e.message;session.ready=true}})
async function auth(){busy.value=true;error.value='';message.value='';try{
 const data=await post(`auth/${authMode.value}/`,{...form.value,token:new URLSearchParams(location.search).get('reset')})
 if(data.user){session.user=data.user;await router.push('/')}
 else {message.value=data.message;authMode.value='login'}
 }catch(e:any){error.value=e.message}finally{busy.value=false}}
async function signout(){await post('auth/logout/');session.user=null;await api('session/');router.push('/')}
</script>
<template>
 <div v-if="!session.ready" class="splash"><Sprout :size="36"/><p>正在打开教学空间…</p></div>
 <div v-else-if="!session.user" class="auth-layout">
  <div class="auth-story"><div class="brand inverse"><span class="brand-icon"><Sprout/></span><b>知序<span>教学工作空间</span></b></div><div class="auth-copy"><span class="eyebrow">MAKE EVERY LESSON COUNT</span><h1>让每一次练习，<br/>都有迹可循。</h1><p>从一张作业，到一份更有针对性的教学计划。<br/>把整理留给工具，把时间留给学生。</p><div class="auth-loop"><span>录入</span><i>→</i><span>批改</span><i>→</i><span>洞察</span><i>→</i><span>复练</span></div></div><small>一对一教学 · 初高中数学</small></div>
  <main class="auth-form"><div class="auth-box"><span class="eyebrow">YOUR TEACHING STUDIO</span><h2>{{authMode==='login'?'欢迎回来':authMode==='register'?'建立你的教学空间':authMode==='forgot'?'找回密码':authMode==='resend'?'重发验证邮件':'设置新密码'}}</h2><p class="muted">独立的学生档案，持续生长的私有题库。</p><div v-if="error" class="notice danger" role="alert">{{error}}</div><div v-if="message" class="notice success">{{message}}</div>
   <form @submit.prevent="auth"><label v-if="authMode==='register'">教师姓名<input v-model="form.name" required autocomplete="name" placeholder="你的称呼"/></label><label v-if="authMode!=='reset'">邮箱地址<input v-model="form.email" type="email" autocomplete="username" required placeholder="teacher@example.com"/></label><label v-if="!['forgot','resend'].includes(authMode)">密码<input v-model="form.password" type="password" :autocomplete="authMode==='login'?'current-password':'new-password'" required :minlength="authMode==='login'?1:8" placeholder="请输入密码"/></label><button class="button primary full" :disabled="busy">{{busy?'正在处理…':authMode==='login'?'进入工作空间':authMode==='register'?'注册并验证邮箱':authMode==='forgot'?'发送重置邮件':authMode==='resend'?'重发验证邮件':'重置密码'}}<ArrowUpRight :size="18"/></button></form>
   <div class="auth-links"><button class="text-button" @click="authMode=authMode==='register'?'login':'register'">{{authMode==='register'?'已有账户，去登录':'创建教师账户'}}</button><button class="text-button" @click="authMode=authMode==='forgot'?'login':'forgot'">{{authMode==='forgot'?'返回登录':'忘记密码？'}}</button></div><button class="text-button resend-link" @click="authMode=authMode==='resend'?'login':'resend'">{{authMode==='resend'?'返回登录':'未收到验证邮件？'}}</button><div class="privacy"><ShieldCheck :size="16"/> 学生与题库资料仅在你的工作空间内可见</div></div></main>
 </div>
 <div v-else class="app" :class="{'print-mode':printMode}">
  <div v-if="mobile" class="nav-scrim" @click="mobile=false"></div>
  <aside class="sidebar" :class="{open:mobile}"><RouterLink to="/" class="brand"><span class="brand-icon"><Sprout :size="25"/></span><b>知序<span>教学工作空间</span></b></RouterLink><button class="mobile-close icon-button" aria-label="关闭导航" @click="mobile=false"><X/></button><div class="workspace-switch"><span class="workspace-avatar">{{session.user.name.slice(0,1)}}</span><div><strong>{{session.user.workspace.name}}</strong><small>个人教师空间</small></div><ChevronDown :size="14"/></div><span class="nav-label">教学管理</span><nav><RouterLink v-for="item in nav" :key="item.to" :to="item.to" :class="{active:item.to==='/'?route.path==='/':route.path.startsWith(item.to)}" @click="mobile=false"><component :is="item.icon" :size="19" stroke-width="1.7"/>{{item.title}}<span v-if="item.to==='/imports'" class="nav-dot"></span></RouterLink></nav><div class="sidebar-bottom"><div class="sidebar-note"><span class="mini-label">一个小提醒</span><p>错题的价值，<br/>藏在下一次做对里。</p><Repeat2 :size="22"/></div><RouterLink to="/settings" class="settings-link" @click="mobile=false"><Settings :size="18"/>工作空间设置</RouterLink><div class="account"><span class="avatar">{{session.user.name.slice(0,1)}}</span><div><strong>{{session.user.name}}</strong><small>数学教师</small></div><button class="icon-button" aria-label="退出登录" @click="signout"><LogOut :size="17"/></button></div></div></aside>
  <div class="main-shell"><header class="topbar"><div class="breadcrumb"><button class="icon-button mobile-menu" aria-label="打开导航" @click="mobile=true"><Menu/></button><span>我的工作空间</span><span class="slash">/</span><b>{{route.meta.title}}</b></div><div class="topbar-right"><span class="private-chip"><ShieldCheck :size="14"/>私有空间</span><span class="top-avatar">{{session.user.name.slice(0,1)}}</span></div></header><main class="page" :class="{printing:printMode}"><RouterView :key="route.fullPath"/></main><footer class="page-footer">知序 · 让教学更有依据<span>每一个进步，都值得被看见</span></footer></div>
 </div>
</template>
