<script setup lang="ts">
import { computed } from 'vue'
import katex from 'katex'
const props=defineProps<{text?:string}>()
const chunks=computed(()=>String(props.text||'').split(/(\$\$[\s\S]*?\$\$|\$[^$\n]+\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\])/g).map((text,index)=>{
 let formula='';let display=false
 if(text.startsWith('$$')){formula=text.slice(2,-2);display=true}
 else if(text.startsWith('$')) formula=text.slice(1,-1)
 else if(text.startsWith('\\(')) formula=text.slice(2,-2)
 else if(text.startsWith('\\[')){formula=text.slice(2,-2);display=true}
 return {text,index,html:formula?katex.renderToString(formula,{throwOnError:false,trust:false,displayMode:display,strict:'ignore'}):''}
}))
</script>
<template><span class="math-text"><template v-for="part in chunks" :key="part.index"><span v-if="part.html" v-html="part.html"></span><template v-else>{{part.text}}</template></template></span></template>
