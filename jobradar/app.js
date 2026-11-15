'use strict';
const {esc,safeUrl,expired,roles,priority,parseRecords,filterJobs,stages}=JobRadarUI;
const $=id=>document.getElementById(id);
const RECORD_KEY='jobradar.personal.v1';
let jobs=[],dataset={},records=Object.create(null),view='priority',storageWritable=true;
const labels={employment:'用工线索',location:'地点',education:'学历',major:'专业',experience:'经验',graduate:'招聘对象',deadline:'报名期限',technical:'技术线索'};
const roleLabels={name:'岗位',department:'单位/部门',employment:'用工方式',education:'学历/学位',major:'专业',age:'年龄',requirements:'条件原文',responsibilities:'岗位职责',count:'人数'};
const viewInfo={priority:['优先核实','与你的技术方向相关，招聘时效和岗位条件仍需核对。','技术相关机会'],all:['全部公告','查看官方公告、岗位原文与附件，了解每条信息的核实状态。','公告列表'],saved:['我的收藏','集中查看值得继续研究的公告。收藏不代表已经投递。','已收藏公告'],tracking:['投递进度','从准备材料到面试，记录你的实际进展。系统不会代你投递。','我的跟进'],sources:['来源健康','区分列表采集、正文获取与附件解析的结果。','官方来源']};
const dateLabel=v=>{if(!v)return '尚未运行';const date=new Date(v);return Number.isNaN(date.valueOf())?'时间未知':new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(date);};
function storageWarning(message){$('storage-warning').hidden=false;$('storage-warning').textContent=message;}
function loadRecords(){try{const raw=localStorage.getItem(RECORD_KEY);if(raw)records=parseRecords(JSON.parse(raw));}catch{storageWritable=false;storageWarning('个人记录无法读取。原记录未被覆盖，本次操作暂存内存；可导出备份，或导入有效备份恢复。');}}
function persist(){
  if(!storageWritable)return false;
  try{localStorage.setItem(RECORD_KEY,JSON.stringify({version:1,records}));return true;}
  catch{storageWritable=false;storageWarning('浏览器无法保存记录，本次改动暂存内存，关闭页面会丢失。请先导出备份。');return false;}
}
function updateRecord(id,patch){
  const job=jobs.find(j=>j.id===id);if(!job)return;
  records[id]={saved:false,stage:'未处理',notes:'',...records[id],...patch,title:job.title,source:job.source,url:job.url};
  persist();updateCounts();
}
function allTracked(){return jobs.filter(j=>records[j.id]?.stage&&records[j.id].stage!=='未处理').length;}
function updateCounts(){
  const counts={priority:jobs.filter(j=>priority(j)).length,all:jobs.length,saved:jobs.filter(j=>records[j.id]?.saved).length,tracking:allTracked()};
  for(const [key,value] of Object.entries(counts))$('nav-'+key).textContent=value;
  $('stat-total').textContent=jobs.length;$('stat-priority').textContent=counts.priority;$('stat-tracking').textContent=counts.tracking;
  const total=(dataset.source_results||[]).length;
  $('stat-sources').textContent=`${dataset.sources_ok||0} / ${total||'—'}`;
  $('source-hint').textContent=dataset.sources_failed?.length?`${dataset.sources_failed.length} 个来源需检查`:'以最近一次采集结果为准';
}
function position(p){return `<details class="position"><summary>${esc(p.fields.name)} · ${esc(p.screening?.verdict)}${p.screening?.priority==='优先核实'?' · 技术相关':''}</summary><p>${(p.screening?.reasons||[]).map(esc).join('<br>')}</p>${Object.entries(p.fields).filter(([k])=>k!=='name').map(([k,v])=>`<p><b>${esc(roleLabels[k]||k)}</b>：${esc(v||'待核实')}</p>`).join('')}<a href="${safeUrl(p.url)}" target="_blank" rel="noopener noreferrer">核对原文${p.row?`（${esc(p.sheet)} 第 ${Number(p.row)} 行）`:`（${esc(p.section)}）`}</a></details>`;}
function evidence(j){
  return `<details class="evidence"><summary>查看条件原文、逐岗位要求与附件 ↓</summary>${Object.entries(j.requirements_evidence||{}).map(([k,v])=>`<p><b>${esc(labels[k]||k)}</b>：${v.length?v.map(e=>`<a href="${safeUrl(e.url)}" target="_blank" rel="noopener noreferrer">${esc(e.text)}</a>`).join('<br>'):'待核实'}</p>`).join('')}${(j.body_positions||[]).filter(()=>j.detail?.status==='ok').map(position).join('')}${(j.attachments||[]).map(a=>`<p><a href="${safeUrl(a.url)}" target="_blank" rel="noopener noreferrer">附件：${esc(a.title)}</a>（${esc(a.status==='ok'?`已解析 ${(a.positions||[]).length} 个岗位`:a.status==='failed'?'解析失败：'+a.error:a.reason||'未解析')}）</p>${j.detail?.status==='ok'&&a.status==='ok'?(a.positions||[]).map(position).join(''):''}`).join('')}<p class="meta">正文核对：${esc(dateLabel(j.detail?.checked_at))} · ${j.detail?.status==='failed'?'本次获取失败，旧片段可能过时；请核对官方原文。':'具体岗位条件仍须核实。'}</p></details>`;
}
function card(j){
  const rec=records[j.id]||{};const related=roles(j).filter(p=>p.screening?.priority==='优先核实'&&p.screening?.verdict!=='明确不符合');
  const isPriority=priority(j),title=isPriority&&related.length===1?related[0].fields.name:j.title;
  const reasons=j.screening?.reasons||['正文尚未分析，条件待核实'];
  const highlights=isPriority?related.flatMap(p=>p.screening?.reasons||[]).slice(0,1):reasons.slice(0,1);
  return `<article class="job${isPriority?' priority':''}" data-id="${esc(j.id)}"><div class="job-header"><div><h3>${esc(title)}</h3><p class="source"><span class="source-icon" aria-hidden="true">▦</span>${esc(j.source)}</p></div><button class="save-button" data-save="${esc(j.id)}" aria-pressed="${rec.saved===true}" aria-label="${rec.saved?'取消收藏':'收藏公告'}：${esc(j.title)}">${rec.saved?'★':'☆'}</button></div><div>${isPriority?'<span class="badge">技术相关 · 优先核实</span>':''}<span class="badge gray">${esc(j.notice_type||'公告类型待核实')}</span><span class="badge${expired(j)?' gray':' amber'}">${expired(j)?'报名已截止':j.deadline?'期限已提取':'招聘时效待核实'}</span><span class="badge gray">${j.detail?.status==='ok'?'正文已获取':'正文待核实'}</span></div><div class="job-facts"><span>截止：${esc(j.deadline||'待核实')}</span><span>标题匹配分：${Number(j.score)||0}</span><span>首次发现：${esc(j.first_seen?.slice(0,10)||'未知')}</span></div><div class="reason"><strong>${esc(highlights[0]||'请核对岗位条件')}</strong>${isPriority?'<p>技术相关不代表符合资格。请展开原文确认用工方式、领域经验和招聘有效期。</p>':''}</div>${evidence(j)}<details class="evidence"><summary>个人备注${rec.notes?' · 已记录':''}</summary><label class="sr-only" for="note-${esc(j.id)}">${esc(j.title)}的个人备注</label><textarea id="note-${esc(j.id)}" class="notes" data-note="${esc(j.id)}" maxlength="4000" placeholder="记录待确认条件、材料准备或联系进展…">${esc(rec.notes||'')}</textarea><p class="meta">仅此浏览器保存，不上传到公开网页。</p></details><div class="job-actions"><a class="button primary" href="${safeUrl(j.url)}" target="_blank" rel="noopener noreferrer">查看官方公告 ↗</a><label>我的进度<select data-stage="${esc(j.id)}" aria-label="${esc(j.title)}的投递进度">${stages.map(s=>`<option${(rec.stage||'未处理')===s?' selected':''}>${s}</option>`).join('')}</select></label></div></article>`;
}
function renderHealth(){
  const names=Object.fromEntries(jobs.map(j=>[j.source_id,j.source]));
  $('health').innerHTML=(dataset.source_results||[]).map(s=>`<article class="health-item"><span class="badge ${s.status==='ok'?'':'amber'}">${s.status==='ok'?'列表采集成功':'列表采集失败'}</span><h3>${esc(names[s.source]||({'zjhrss':'浙江省人力资源和社会保障厅'}[s.source])||s.source)}</h3><p>${s.status==='ok'?`${Number(s.notices)||0} 条去重候选公告`:esc(s.error||'原因未知')}</p></article>`).join('')||'<div class="empty">尚无来源健康记录。</div>';
  if(dataset.details_summary)$('health').innerHTML+=`<article class="health-item"><h3>正文与附件</h3><p>正文成功 ${Number(dataset.details_summary.ok)||0} 条，失败 ${(dataset.details_summary.failed||[]).length} 条；岗位附件解析失败 ${(dataset.attachment_failures||[]).length} 项。</p><p class="meta">详情请查看对应公告的条件原文。登录跳转与访问失败不会当作核实成功。</p></article>`;
}
function render(){
  const info=viewInfo[view];$('view-title').textContent=info[0];$('view-description').textContent=info[1];$('result-title').textContent=info[2];
  for(const button of document.querySelectorAll('[data-view]')){if(button.dataset.view===view)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');}
  const sourceView=view==='sources';$('browser-tools').hidden=sourceView;$('health').hidden=!sourceView;$('list').hidden=sourceView;
  if(sourceView){$('result-count').textContent='最近一次采集';renderHealth();return;}
  const filtered=filterJobs(jobs,{view,q:$('q').value,source:$('source').value,deadline:$('deadline').value,type:$('type').value},records);
  filtered.sort((a,b)=>$('sort').value==='score'?(b.score||0)-(a.score||0):String(b.first_seen||'').localeCompare(String(a.first_seen||'')));
  $('result-count').textContent=`${filtered.length} 条公告`;
  $('list').innerHTML=filtered.length?filtered.map(card).join(''):`<div class="empty"><span aria-hidden="true">◎</span><h3>${view==='saved'?'还没有收藏公告':view==='tracking'?'还没有跟进记录':'当前条件下暂无公告'}</h3><p>${view==='saved'?'在公告右上角点星号，把值得继续研究的机会放到这里。':view==='tracking'?'在公告下方选择实际投递进度，再到这里集中跟进。':'可重置筛选或查看全部公告。未命中不代表不存在符合条件的岗位。'}</p></div>`;
}
async function loadDailySummary(data){
  try{
    const response=await fetch('./daily-summary.json',{cache:'no-store'});
    if(!response.ok)throw Error('HTTP '+response.status);
    const summary=await response.json();
    if(summary.schema_version!==1||!data.run_id||summary.run_id!==data.run_id||summary.updated_at!==data.updated_at)throw Error('摘要和公告批次不一致');
    if(!['ok','partial_failure'].includes(summary.status)||!Array.isArray(summary.new_positions)||!Array.isArray(summary.changed_positions))throw Error('摘要格式异常');
    const jobsFailed=(data.sources_failed||[]).length||(data.details_summary?.failed||[]).length||(data.attachment_failures||[]).length;
    if(jobsFailed&&summary.status==='ok')throw Error('摘要健康状态与采集错误不一致');
    const health=summary.status==='partial_failure'?'部分采集失败，未取得的来源不能视为无新增':'采集正常';
    $('daily-summary-status').textContent=`最近采集：${dateLabel(summary.updated_at)}（北京时间） · ${health} · 新增 ${summary.new_positions.length} 个 / 变化 ${summary.changed_positions.length} 个`;
    const item=(p,kind)=>`<article class="evidence"><h3>${esc(kind)}：${esc(p.title)}</h3><p>${esc(p.source)} · 截止：${esc(p.deadline||'待核实')}</p><p>匹配依据：${(p.match_reasons||[]).map(esc).join('；')||'待核实'}</p><p>已确认障碍：${(p.confirmed_obstacles||[]).map(esc).join('；')||'尚未确认；不代表符合全部条件'}</p><p>待核实：${(p.unverified_conditions||[]).map(esc).join('；')||'请核对官方原文'}</p><a href="${safeUrl(p.official_url)}" target="_blank" rel="noopener noreferrer">查看官方来源 ↗</a></article>`;
    $('daily-summary-items').innerHTML=(summary.new_positions.length?'':'<p>本次无新增重点候选</p>')+summary.new_positions.map(p=>item(p,'新增')).join('')+summary.changed_positions.map(p=>item(p,'变化')).join('');
  }catch(error){$('daily-summary-status').textContent='增量摘要暂不可用：'+error.message+'。公告列表仍可查看。';$('daily-summary-items').innerHTML='';}
}
async function loadData(){
  $('reload').disabled=true;
  try{
    const response=await fetch('./jobs.json',{cache:'no-store'});if(!response.ok)throw Error('HTTP '+response.status);
    const data=await response.json();if(!Array.isArray(data.jobs)||data.jobs.some(j=>typeof j.id!=='string'||typeof j.title!=='string'))throw Error('公告数据格式异常');
    dataset=data;jobs=data.jobs;
    const selected=$('source').value;
    $('source').innerHTML='<option value="all">全部来源</option>'+[...new Map(jobs.map(j=>[j.source_id,j.source])).entries()].map(([id,name])=>`<option value="${esc(id)}">${esc(name)}</option>`).join('');
    $('source').value=[...new Set(jobs.map(j=>j.source_id))].includes(selected)?selected:'all';
    $('meta').textContent=`数据更新 ${dateLabel(data.updated_at)}（北京时间） · 正文成功 ${data.details_summary?.ok||0} 条 / 失败 ${data.details_summary?.failed?.length||0} 条${data.sources_failed?.length?' · 部分来源失败，见来源健康':''}`;
    updateCounts();render();
    await loadDailySummary(data);
  }catch(error){$('meta').textContent='数据读取失败：'+error.message+'。可点击刷新重试。';if(!jobs.length)$('list').innerHTML='<div class="empty"><h3>暂时无法读取招聘数据</h3><p>检查网络后刷新。已有个人记录保留在此浏览器中。</p></div>';}
  finally{$('reload').disabled=false;}
}
function navigate(next){view=next;for(const id of ['q','source','deadline','type','sort'])$(id).value=id==='q'?'':id==='sort'?'recent':'all';render();}
for(const button of document.querySelectorAll('[data-view]'))button.addEventListener('click',()=>navigate(button.dataset.view));
for(const id of ['q','source','deadline','type','sort'])$(id).addEventListener('input',render);
$('reset').addEventListener('click',()=>navigate(view));$('reload').addEventListener('click',loadData);
$('list').addEventListener('click',event=>{const button=event.target.closest('[data-save]');if(!button)return;const id=button.dataset.save;updateRecord(id,{saved:!records[id]?.saved});render();});
$('list').addEventListener('change',event=>{const id=event.target.dataset.stage;if(!id)return;updateRecord(id,{stage:event.target.value});$('record-message').textContent=storageWritable?'进度已保存在此浏览器。':'进度暂存内存，请导出备份。';if(view==='tracking')render();});
$('list').addEventListener('input',event=>{const id=event.target.dataset.note;if(!id)return;updateRecord(id,{notes:event.target.value.slice(0,4000)});$('record-message').textContent=storageWritable?'备注已保存在此浏览器。':'备注暂存内存，请导出备份。';});
$('export').addEventListener('click',()=>{const blob=new Blob([JSON.stringify({version:1,exported_at:new Date().toISOString(),records},null,2)],{type:'application/json'});const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='jobradar-personal-'+JobRadarUI.today()+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);$('record-message').textContent='个人记录已导出。备份包含你的备注，请妥善保存。';});
$('import').addEventListener('change',async event=>{
  const file=event.target.files?.[0];if(!file)return;
  try{if(file.size>1000000)throw Error('备份大于 1 MB');const imported=parseRecords(JSON.parse(await file.text()));records=Object.assign(Object.create(null),records,imported);storageWritable=true;const stored=persist();if(stored)$('storage-warning').hidden=true;updateCounts();render();$('record-message').textContent=`已合并 ${Object.keys(imported).length} 条记录；同一公告采用导入内容。${stored?'':'当前暂存内存，请导出备份。'}`;}
  catch(error){$('record-message').textContent='导入失败：'+error.message+'。现有记录未修改。';}
  event.target.value='';
});
loadRecords();loadData();
