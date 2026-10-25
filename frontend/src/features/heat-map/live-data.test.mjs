import test from 'node:test';
import assert from 'node:assert/strict';
import {toHeatMapData,placeEvent,priorityFor,calendarFor,mondayOf,parseDate,sampleSource,busiestWeekStart} from './live-data.mjs';
import {dailyLoad,classify} from './model.mjs';

const event=(id,title,start,end,extra={})=>({id,title,start,end,all_day:false,type:'class',prep_hours:0,stress:2,...extra});
const analysis={
 meta:{start:'2026-10-12',end:'2026-10-25',timezone:'America/New_York',threshold_hours:50,median_weekly_hours:20,classifier:'gemma',unplaced_prep_hours:0},
 days:[],
 hell_weeks:[{start:'2026-10-15',end:'2026-10-23',total_hours:61,peak_start:'2026-10-16',peak_end:'2026-10-22',peak_hours:57.5,
  key_events:[{event_id:'mid',title:'CHEM Midterm',type:'exam',date:'2026-10-20',prep_hours:10,stress:9}],
  report:{headline:'☠️ HELL WEEK: Oct 15 – Oct 23',forecast:'Storms.',advisories:['Start early.'],source:'gemma'}}],
 events:[
  event('lec','CHEM Lecture','2026-10-19T09:00:00-04:00','2026-10-19T09:50:00-04:00'),
  event('mid','CHEM Midterm','2026-10-20T19:00:00-04:00','2026-10-20T21:00:00-04:00',{type:'exam',prep_hours:10,stress:9}),
  event('due','Project due','2026-10-22T00:00:00-04:00','2026-10-23T00:00:00-04:00',{all_day:true,type:'deadline',stress:7}),
  event('late','Late party','2026-10-24T01:00:00-04:00','2026-10-24T03:00:00-04:00',{type:'social',stress:1}),
  event('shift','Cafe shift','2026-10-17T10:00:00-04:00','2026-10-17T17:00:00-04:00',{type:'work',stress:3}),
 ],
 prep_blocks:[{event_id:'mid',title:'CHEM Midterm',date:'2026-10-19',start_hour:10,end_hour:16},{event_id:'mid',title:'CHEM Midterm',date:'2026-10-18',start_hour:23,end_hour:25.5}],
};

test('week 0 starts on the Monday of the worst hell week',()=>{const data=toHeatMapData(analysis);assert.equal(data.base.getDay(),1);assert.equal(data.base.getDate(),19);assert.equal(data.kind,'live');assert.equal(data.timezone,'America/New York');});
test('events land on the right day, hour and calendar',()=>{const week=toHeatMapData(analysis).eventsFor(0);const lec=week.find(e=>e.id==='lec');assert.deepEqual([lec.day,lec.start,lec.type,lec.priority],[0,9,'Classes',1]);assert.ok(Math.abs(lec.end-(9+50/60))<1e-9);const mid=week.find(e=>e.id==='mid');assert.deepEqual([mid.day,mid.start,mid.end,mid.priority],[1,19,21,3]);});
test('after-midnight events belong to the evening before',()=>{const late=toHeatMapData(analysis).eventsFor(0).find(e=>e.id==='late');assert.deepEqual([late.day,late.start,late.end],[4,25,27]);});
test('all-day deadlines are visible but add no hours',()=>{const due=toHeatMapData(analysis).eventsFor(0).find(e=>e.id==='due');assert.equal(due.allDay,true);assert.equal(due.start,due.end);assert.equal(dailyLoad([due]),0);});
test('prep blocks become high-priority study events that count toward load',()=>{const data=toHeatMapData(analysis);const monday=data.eventsFor(0).filter(e=>e.day===0);const prep=monday.find(e=>e.prep);assert.equal(prep.title,'Prep: CHEM Midterm');assert.equal(prep.priority,3);assert.equal(dailyLoad(monday),Math.round((50/60+6)/6*100));const sunday=data.eventsFor(-1).find(e=>e.prep);assert.deepEqual([sunday.day,sunday.start,sunday.end],[6,23,25.5]);});
test('reportFor finds the hell week overlapping a week, and nothing elsewhere',()=>{const data=toHeatMapData(analysis);assert.equal(data.reportFor(0).report.source,'gemma');assert.equal(data.reportFor(-1).peak_hours,57.5);assert.equal(data.reportFor(2),null);});
test('eventsFor returns copies so the page can annotate them freely',()=>{const data=toHeatMapData(analysis);data.eventsFor(0)[0].title='changed';assert.notEqual(data.eventsFor(0)[0].title,'changed');});
test('mapping helpers',()=>{assert.deepEqual([1,4,6,7,10].map(priorityFor),[1,2,2,3,3]);assert.equal(calendarFor('exam'),'Classes');assert.equal(calendarFor('social'),'Campus life');assert.equal(calendarFor('mystery'),'Me time');assert.equal(mondayOf(parseDate('2026-10-25')).getDate(),19);assert.deepEqual(placeEvent(analysis.events[0]).start,9);});
test('without hell weeks the view anchors on the busiest 7 days, else the range start',()=>{const day=(date,total_hours)=>({date,total_hours,scheduled_hours:0,prep_hours:0,breakdown:[]});const days=[1,0,0,0,0,0,0,0,9,9,0].map((h,i)=>day(`2026-11-${String(2+i).padStart(2,'0')}`,h));assert.equal(busiestWeekStart(days),'2026-11-05');const busy=toHeatMapData({...analysis,days,hell_weeks:[]});assert.equal(busy.base.getMonth(),10);assert.equal(busy.base.getDate(),2);const empty=toHeatMapData({...analysis,hell_weeks:[]});assert.equal(empty.base.getDate(),12);assert.equal(empty.reportFor(0),null);});
test('the sample source still works as the offline fallback',()=>{assert.equal(sampleSource.kind,'sample');assert.ok(sampleSource.eventsFor(0).length>10);assert.equal(sampleSource.reportFor(0),null);assert.equal(classify([0]).label,'Chill week');});
test('the /calendars handoff carries only ids, titles and times, and is read once',async()=>{const {giveHandoff,takeHandoff,HANDOFF_KEY}=await import('./live-data.mjs?handoff');const store=new Map(),storage={getItem:k=>store.get(k)??null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)};const parsed={provider:'google',start:'2026-10-01',end:'2026-10-31',timezone:'America/New_York',events:[{provider:'google',calendar_id:'primary',calendar_name:'School',id:'a',title:'Midterm',start:'2026-10-20T19:00:00-04:00',end:'2026-10-20T21:00:00-04:00',all_day:false,duration_hours:2,location:'Hall 1',description:'notes'}]};assert.equal(giveHandoff(storage,parsed),true);assert.ok(!store.get(HANDOFF_KEY).includes('Hall 1'));const first=takeHandoff(storage);assert.deepEqual(first,{source:'events',events:[{id:'a',title:'Midterm',start:'2026-10-20T19:00:00-04:00',end:'2026-10-20T21:00:00-04:00',all_day:false}],start:'2026-10-01',end:'2026-10-31',tz:'America/New_York'});assert.equal(store.has(HANDOFF_KEY),false);assert.deepEqual(takeHandoff(storage),first);});
test('no handoff means null, and junk is ignored',async()=>{const {takeHandoff}=await import('./live-data.mjs?junk');const storage={getItem:()=>'{"source":"nope"}',removeItem:()=>{}};assert.equal(takeHandoff(storage),null);});
test('the connected-calendar window is local dates, two weeks back to four months ahead, within the 366-day cap',async()=>{const {connectedRange,CONNECTED_DAYS_BEFORE,CONNECTED_DAYS_AFTER}=await import('./live-data.mjs');assert.deepEqual(connectedRange(new Date(2026,9,25,23,30)),{start:'2026-10-11',end:'2027-02-22'});assert.deepEqual(connectedRange(new Date(2026,0,3)),{start:'2025-12-20',end:'2026-05-03'});assert.ok(CONNECTED_DAYS_BEFORE+CONNECTED_DAYS_AFTER<=366);});
