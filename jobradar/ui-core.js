(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.JobRadarUI=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
  const stages=['未处理','待核实','准备投递','已投递','面试中','已结束'];
  const today=()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai'}).format(new Date());
  const expired=(j,date=today())=>Boolean(j.deadline&&j.deadline<date);
  const roles=j=>j.detail?.status==='ok'?[...(j.body_positions||[]),...(j.attachments||[]).filter(a=>a.status==='ok').flatMap(a=>a.positions||[])]:[];
  const priority=(j,date=today())=>!expired(j,date)&&roles(j).some(p=>p.screening?.priority==='优先核实'&&p.screening?.verdict!=='明确不符合');
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const safeUrl=u=>{try{const v=new URL(u);return ['http:','https:'].includes(v.protocol)?esc(v.href):'#';}catch{return '#';}};
  function parseRecords(payload){
    if(payload?.version!==1||!payload.records||Array.isArray(payload.records)||typeof payload.records!=='object')throw Error('记录格式不正确');
    const entries=Object.entries(payload.records);if(entries.length>5000)throw Error('记录数量超出限制');
    const records=Object.create(null);
    for(const [id,r] of entries){
      if(!/^[a-zA-Z0-9_-]{1,80}$/.test(id)||['__proto__','constructor','prototype'].includes(id)||!r||typeof r!=='object'||!stages.includes(r.stage??'未处理'))throw Error('记录字段不正确');
      records[id]={saved:r.saved===true,stage:r.stage??'未处理',notes:String(r.notes??'').slice(0,4000),title:String(r.title??'').slice(0,250),source:String(r.source??'').slice(0,150),url:String(r.url??'').slice(0,2000)};
    }
    return records;
  }
  function filterJobs(jobs,{view='all',q='',source='all',deadline='all',type='all'}={},records={},date=today()){
    const query=q.trim().toLowerCase();
    return jobs.filter(j=>{
      const text=[j.title,j.source,...roles(j).flatMap(p=>Object.values(p.fields||{}))].join(' ').toLowerCase();
      return (!query||text.includes(query))&&(source==='all'||j.source_id===source)&&
        (deadline==='all'||deadline==='unknown'&&!j.deadline||deadline==='expired'&&expired(j,date)||deadline==='not-expired'&&!expired(j,date))&&
        (type==='all'||type==='failed'&&j.detail?.status==='failed'||type==='notice'&&j.notice_type==='招聘公告'||type==='process'&&['录用公示/考察','考试/流程通知'].includes(j.notice_type))&&
        (view==='all'||view==='priority'&&priority(j,date)||view==='saved'&&records[j.id]?.saved||view==='tracking'&&records[j.id]?.stage&&records[j.id].stage!=='未处理');
    });
  }
  return {stages,today,expired,roles,priority,esc,safeUrl,parseRecords,filterJobs};
});
