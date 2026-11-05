import { reactive } from 'vue'

export const session = reactive<{user:any; ready:boolean}>({user:null,ready:false})
let csrf = ''
function errorText(value:any):string {
  if(typeof value==='string') return value
  if(Array.isArray(value)) return value.map(errorText).join('；')
  if(value && typeof value==='object') return Object.entries(value).map(([k,v])=>`${k==='detail'?'':k+'：'}${errorText(v)}`).join('；')
  return '操作失败，请稍后重试。'
}
export async function api<T=any>(path:string, options:RequestInit={}):Promise<T> {
  const headers:Record<string,string>={'X-CSRFToken':csrf,...options.headers as Record<string,string>}
  if(options.body && !(options.body instanceof FormData)) headers['Content-Type']='application/json'
  const response=await fetch('/api/'+path,{...options,headers,credentials:'same-origin'})
  const data=await response.json().catch(()=>({detail:'服务暂时不可用，请检查网络。'}))
  if(!response.ok) throw new Error(errorText(data))
  if(data.csrf) csrf=data.csrf
  return data
}
export const post=<T=any>(path:string,data:any={})=>api<T>(path,{method:'POST',body:JSON.stringify(data)})
export const patch=<T=any>(path:string,data:any)=>api<T>(path,{method:'PATCH',body:JSON.stringify(data)})
export async function loadSession(){const data=await api('session/');session.user=data.user;session.ready=true}
export const kindName:Record<string,string>={single:'单选题',multiple:'多选题',fill:'填空题',solution:'解答题',proof:'证明题'}
export const statusName:Record<string,string>={uploaded:'待识别',queued:'排队中',processing:'识别中',review:'待审核',blocked:'待处理',failed:'处理失败',committed:'已归档',draft:'草稿',approved:'已入库',published:'已发布',pending:'待复核',final:'已定分'}
export const materialName:Record<string,string>={blank:'空白试卷',with_answers:'附参考答案',answered:'学生已作答'}
export function dateText(value:string){return value?new Date(value).toLocaleDateString('zh-CN',{month:'2-digit',day:'2-digit'}):'未设置'}
export function today(){return new Date().toLocaleDateString('sv-SE')}
