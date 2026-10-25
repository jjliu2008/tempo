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

test('advice keeps only text for events that were asked about',()=>{
 assert.deepEqual(parseAdvice({advice:{mid:' Lock in. ',ghost:'x',party:'',study:7}},week),{mid:'Lock in.'});
 assert.deepEqual(parseAdvice(null,week),{});
 assert.deepEqual(parseAdvice({advice:['a']},week),{});
 assert.equal(adviceRequest(week).context.events.length,3);
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
