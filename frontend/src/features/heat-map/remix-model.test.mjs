import test from 'node:test';
import assert from 'node:assert/strict';
import {applyRemixPlan,parseRemixPlan,remixRequest,scheduledHours,mixKey} from './remix-model.mjs';
import {parseAdvice,adviceRequest} from './advice-model.mjs';
import {parseReply} from './gemma-reply.mjs';

const week=[
 {id:'mid',day:1,start:10,end:12,type:'Classes',title:'CHEM Midterm',priority:3},
 {id:'party',day:3,start:22,end:26,type:'Campus life',title:'House party',priority:1},
 {id:'study',day:2,start:13,end:15,type:'Classes',title:'Library',priority:2},
];

test('a plan can only touch real events, and never removes a non-negotiable one',()=>{
 const plan=parseRemixPlan({remove:[{id:'mid',detail:'x'},{id:'ghost'},{id:'party',detail:'Skip it'}],change:[{id:'study',title:'Study group'},{id:'ghost',title:'nope'}],add:[]},week);
 assert.deepEqual(plan.remove.map(r=>r.id),['party']);
 assert.deepEqual(plan.change.map(c=>c.id),['study']);
 const result=applyRemixPlan(week,{...plan,remove:[{id:'mid',detail:''},...plan.remove]},'lazy');
 assert.ok(result.events.some(e=>e.id==='mid'),'priority 3 survives even a forced removal');
 assert.ok(!result.events.some(e=>e.id==='party'));
 assert.deepEqual(result.changes.map(c=>c.kind).sort(),['changed','removed']);
});

test('added blocks are bounded, typed, and skipped when they overlap an existing event',()=>{
 const plan=parseRemixPlan({add:[
  {day:1,start:10.5,end:11.5,title:'Overlaps midterm',type:'Classes',priority:3},
  {day:0,start:18,end:19.5,title:'Dinner with the lab group',type:'Campus life',priority:2,detail:'Meet people'},
  {day:0,start:7,end:9,title:'Too early'},
  {day:0,start:18,end:23,title:'Too long'},
  {day:9,start:18,end:19,title:'Bad day'},
  {day:2,start:18,end:19,title:'Odd type',type:'Raving'},
 ]},week);
 assert.deepEqual(plan.add.map(a=>a.title),['Overlaps midterm','Dinner with the lab group','Odd type']);
 assert.equal(plan.add[2].type,'Me time');
 const result=applyRemixPlan(week,plan,'extrovert');
 assert.ok(!result.events.some(e=>e.title==='Overlaps midterm'));
 const dinner=result.events.find(e=>e.title==='Dinner with the lab group');
 assert.equal(dinner.change,'added');
 assert.equal(result.changes.find(c=>c.id===dinner.id).detail,'Meet people');
});

test('no plan yet, or a failed one, leaves the original week as it was',()=>{
 assert.deepEqual(applyRemixPlan(week,undefined,'lazy').events,week);
 assert.deepEqual(applyRemixPlan(week,null,'lazy').changes,[]);
 assert.equal(parseRemixPlan('nope',week),null);
 assert.equal(scheduledHours(week),8);
});

test('the request sends only what the plan needs and marks titles as untrusted',()=>{
 const request=remixRequest('grind',[{...week[0],location:'Room 4'}],{style:'introvert',likes:[]});
 assert.deepEqual(Object.keys(request.context.events[0]).sort(),['day','end','id','priority','start','title','type']);
 assert.match(request.system_prompt,/untrusted/);
});

test('both independent controls shape the goal Gemma is given',()=>{
 const lazyIntro=remixRequest({effort:'lazy',social:'introvert'},week,null).prompt,grindExtro=remixRequest({effort:'grind',social:'extrovert'},week,null).prompt;
 assert.notEqual(lazyIntro,grindExtro);
 assert.match(lazyIntro,/lighter week/);assert.match(lazyIntro,/alone/);
 assert.match(grindExtro,/focused week/);assert.match(grindExtro,/group study/);
 assert.equal(mixKey({effort:'lazy',social:'introvert'}),'lazy-introvert');
});


test('Gemma replies parse with or without a Markdown fence',()=>{
 assert.deepEqual(parseReply('```json\n{"a":1}\n```'),{a:1});
 assert.deepEqual(parseReply('{"a":1}'),{a:1});
 assert.throws(()=>parseReply('sure!'));
});

test('scheduled hours never show float noise',()=>{
 assert.equal(scheduledHours([{start:0,end:.1},{start:0,end:.2}]),.3);
 assert.equal(scheduledHours([{start:10,end:10+1/3},{start:12,end:12+1/3}]),.67);
});

test('skips and lock-ins always lead with the plain words, even if Gemma forgot them',()=>{
 const plan=parseRemixPlan({remove:[{id:'party',detail:'nobody will miss it'}],change:[{id:'study',priority:3,detail:'the exam is Friday'}]},week);
 const {changes}=applyRemixPlan(week,plan,{effort:'grind',social:'introvert'});
 assert.equal(changes.find(c=>c.kind==='removed').detail,'Skip: nobody will miss it');
 assert.equal(changes.find(c=>c.kind==='changed').detail,'Lock in: the exam is Friday');
 const kept=applyRemixPlan(week,parseRemixPlan({remove:[{id:'party',detail:'Skip: already clear'}]},week),{effort:'lazy',social:'introvert'}).changes[0].detail;
 assert.equal(kept,'Skip: already clear');
});

test('the chosen mix reaches both the remix and the hover advice',()=>{
 const mix={effort:'lazy',social:'introvert'};
 assert.match(adviceRequest(week,null,mix).system_prompt,/lighter week/);
 assert.doesNotMatch(adviceRequest(week,null,null).system_prompt,/lighter week/);
});

test('advice carries a verdict per event, and a non-negotiable event can never be a skip',()=>{
 const found=parseAdvice({advice:{mid:{verdict:'skip',line:'Tempting, but no'},party:{verdict:'skip',line:'Nobody needs this'},study:{verdict:'maybe',line:'x'}}},week);
 assert.deepEqual(found,{mid:{verdict:'lock',text:'Tempting, but no'},party:{verdict:'skip',text:'Nobody needs this'}});
});

test('a lazy remix can never end longer than the original week',()=>{
 const busy=[...week,{id:'x1',day:4,start:9,end:11,type:'Classes',title:'Seminar',priority:1},{id:'x2',day:5,start:9,end:11,type:'Classes',title:'Optional lab',priority:1}];
 const greedy=parseRemixPlan({remove:[{id:'x1',detail:'Skip it'}],add:[{day:0,start:8,end:11,title:'Recovery',type:'Me time'},{day:1,start:14,end:17,title:'Nap',type:'Me time'},{day:2,start:18,end:21,title:'Quiet night',type:'Me time'}]},busy);
 for(const effort of ['lazy','balanced','grind']){
  const {events}=applyRemixPlan(busy,greedy,{effort,social:'balanced'});
  const delta=scheduledHours(events)-scheduledHours(busy);
  if(effort==='lazy')assert.ok(delta<0,`lazy changed hours by ${delta}`);
  if(effort==='balanced')assert.ok(delta<=2);
 }
 const added=applyRemixPlan(busy,greedy,{effort:'lazy',social:'balanced'}).changes.filter(c=>c.kind==='added');
 assert.deepEqual(added,[],'lazy only skips, it never adds');
});
