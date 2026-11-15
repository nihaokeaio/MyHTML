const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const ui=require('../jobradar/ui-core.js');
const role={fields:{name:'软件工程师',requirements:'Qt C++'},screening:{priority:'优先核实',verdict:'需要人工核实',reasons:[]},url:'https://example.com/plan.xls',sheet:'计划',row:10};
const base={title:'官方公开招聘',source:'官方',source_id:'s',score:0,first_seen:'2026-11-15',url:'https://example.com/a',screening:{verdict:'需要人工核实',reasons:[]}};
const jobs=[{...base,id:'a',detail:{status:'ok'},attachments:[{title:'岗位表',url:role.url,status:'ok',positions:[role]}]},
 {...base,id:'b',title:'<img src=x onerror=alert(1)>',detail:{status:'failed'},body_positions:[role]},
 {...base,id:'c',screening:{verdict:'明确不符合',reasons:['流程公告']},notice_type:'录用公示/考察',detail:{status:'ok'}},
 {...base,id:'d',deadline:'2000-01-01',detail:{status:'ok'},body_positions:[role]}];
assert.equal(ui.filterJobs(jobs,{view:'priority'}).length,1);
assert.equal(ui.filterJobs(jobs,{view:'priority',q:'qt'}).length,1);
assert.equal(ui.filterJobs(jobs,{type:'failed'}).length,1);
assert.equal(ui.filterJobs(jobs,{deadline:'expired'}).length,1);
assert.equal(ui.filterJobs(jobs,{deadline:'unknown'}).length,3);
assert.equal(ui.filterJobs(jobs,{source:'other'}).length,0);
assert.equal(ui.filterJobs(jobs,{view:'saved'},{a:{saved:true}}).length,1);
assert.equal(ui.filterJobs(jobs,{view:'tracking'},{a:{stage:'已投递'}}).length,1);
assert.equal(ui.safeUrl('javascript:alert(1)'),'#');
assert.throws(()=>ui.parseRecords({version:2,records:{}}));
assert.throws(()=>ui.parseRecords(JSON.parse('{"version":1,"records":{"__proto__":{}}}')));
assert.throws(()=>ui.parseRecords({version:1,records:{a:{stage:'已录用但尚未确认'}}}));
assert.equal(ui.parseRecords({version:1,records:{a:{notes:'x'.repeat(5000)}}}).a.notes.length,4000);
const dataset={run_id:'test-batch',updated_at:'2026-11-15T05:00:00+00:00',jobs,source_results:[{source:'blocked',status:'failed',error:'403 <script>'}],sources_failed:[{source:'blocked'}]};
async function boot(storage,summary=null){
 const ids=['daily-summary-status','daily-summary-items','q','source','deadline','type','sort','list','health','meta','browser-tools','view-title','view-description','result-title','result-count','storage-warning','reload','reset','export','import','record-message','stat-total','stat-priority','stat-tracking','stat-sources','source-hint','nav-priority','nav-all','nav-saved','nav-tracking'];
 const els=Object.fromEntries(ids.map(id=>[id,{value:['source','deadline','type'].includes(id)?'all':id==='sort'?'recent':'',innerHTML:'',textContent:'',dataset:{},hidden:false,listeners:{},addEventListener(type,fn){this.listeners[type]=fn;}}]));
 const nav=['priority','all','saved','tracking','sources'].map(view=>({dataset:{view},attrs:{},listeners:{},setAttribute(k,v){this.attrs[k]=v},removeAttribute(k){delete this.attrs[k]},addEventListener(type,fn){this.listeners[type]=fn}}));
 const context={JobRadarUI:ui,URL,Intl,Date,Blob,setTimeout,localStorage:storage,document:{getElementById:id=>els[id],querySelectorAll:()=>nav},fetch:url=>Promise.resolve({ok:true,json:()=>Promise.resolve(url.includes('daily-summary')?(summary||{schema_version:1,run_id:dataset.run_id,updated_at:dataset.updated_at,status:'partial_failure',new_positions:[],changed_positions:[]}):dataset)})};
 vm.createContext(context);vm.runInContext(fs.readFileSync('jobradar/app.js','utf8'),context);await new Promise(setImmediate);
 return {els,nav,context};
}
(async()=>{
 const saved=new Map(),storage={getItem:k=>saved.get(k)||null,setItem:(k,v)=>saved.set(k,v)};
 let {els,nav,context}=await boot(storage);
 assert.equal((els.list.innerHTML.match(/<article /g)||[]).length,1);
 assert.ok(els.list.innerHTML.includes('第 10 行'));
 nav.find(n=>n.dataset.view==='all').listeners.click();
 assert.equal((els.list.innerHTML.match(/<article /g)||[]).length,4);
 assert.ok(els.list.innerHTML.includes('&lt;img'));assert.ok(!els.list.innerHTML.includes('<img src=x'));
 els.list.listeners.click({target:{closest:()=>({dataset:{save:'a'}})}});
 assert.equal(JSON.parse(saved.get('jobradar.personal.v1')).records.a.saved,true);
 els.list.listeners.change({target:{dataset:{stage:'a'},value:'已投递'}});
 els.list.listeners.input({target:{dataset:{note:'a'},value:'需要确认运动控制经验'}});
 assert.equal(els['stat-tracking'].textContent,1);
 const refreshed=await boot(storage);assert.equal(refreshed.els['nav-saved'].textContent,1);
 refreshed.nav.find(n=>n.dataset.view==='tracking').listeners.click();
 assert.ok(refreshed.els.list.innerHTML.includes('需要确认运动控制经验'));
 refreshed.nav.find(n=>n.dataset.view==='sources').listeners.click();
 assert.ok(refreshed.els.health.innerHTML.includes('&lt;script&gt;'));
 const original=saved.get('jobradar.personal.v1');
 await els.import.listeners.change({target:{files:[{size:2,text:async()=>'{bad'}],value:'file'}});
 assert.equal(saved.get('jobradar.personal.v1'),original);
 const broken=new Map([['jobradar.personal.v1','{corrupt']]);
 const recovery=await boot({getItem:k=>broken.get(k),setItem:(k,v)=>broken.set(k,v)});
 recovery.els.list.listeners.click({target:{closest:()=>({dataset:{save:'a'}})}});
 assert.equal(broken.get('jobradar.personal.v1'),'{corrupt');assert.equal(recovery.els['storage-warning'].hidden,false);
 const summaryFixture={schema_version:1,run_id:dataset.run_id,updated_at:dataset.updated_at,status:'partial_failure',new_positions:[{title:'<script>新增岗位</script>',source:'官方来源',official_url:'https://example.com/new',match_reasons:['Qt'],unverified_conditions:['年龄']}],changed_positions:[]};
 const added=await boot(storage,summaryFixture);assert.ok(added.els['daily-summary-items'].innerHTML.includes('&lt;script&gt;新增岗位'));assert.ok(added.els['daily-summary-items'].innerHTML.includes('https://example.com/new'));
 const stale=await boot(storage,{...summaryFixture,run_id:'old-batch'});assert.ok(stale.els['daily-summary-status'].textContent.includes('批次不一致'));assert.equal(stale.els['daily-summary-items'].innerHTML,'');
 const masked=await boot(storage,{...summaryFixture,status:'ok'});assert.ok(masked.els['daily-summary-status'].textContent.includes('健康状态'));
 console.log('Page tests passed: real rendering, filters, stale/expired exclusion, row evidence, XSS, record persistence, import validation and corrupted-storage preservation.');
})().catch(e=>{console.error(e);process.exitCode=1});
