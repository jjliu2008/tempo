// Turns the backend's calendar analysis into the heat map's data source:
// events as {id, day, start, end, type, title, priority} per week, where week 0
// starts on the Monday of the worst hell week. Prep becomes "Prep: …" blocks so
// the hidden work shows up in the same 6h/day load as everything else.
import {base as sampleBase,eventsFor as sampleEventsFor} from './college-data.mjs';

const CALENDAR_FOR_TYPE={exam:'Classes',quiz:'Classes',deadline:'Classes',class:'Classes',meeting:'Campus life',social:'Campus life',work:'Campus life',other:'Me time'};
const DAY_MS=86400000;
// After-midnight hours (+1) belong to the evening before, as on the grid.
const NIGHT_OWL_UNTIL=4;
// All-day items (deadlines) sit at 11:30pm with no duration: visible, no fake hours.
const ALL_DAY_AT=23.5;

// /calendars hands its parsed events to /schedule through sessionStorage: ids,
// titles and times only, read once per page load and then removed.
export const HANDOFF_KEY='hellweek-handoff-v1';
let handoff;
export function makeHandoff(parsed){return {source:'events',events:parsed.events.map(({id,title,start,end,all_day})=>({id,title,start,end,all_day})),start:parsed.start,end:parsed.end,tz:parsed.timezone};}
export function giveHandoff(storage,parsed){handoff=undefined;try{storage.setItem(HANDOFF_KEY,JSON.stringify(makeHandoff(parsed)));return true;}catch{return false;}}
// Cached per page load, so React StrictMode's double effect run still sees it.
export function takeHandoff(storage){if(handoff!==undefined)return handoff;handoff=null;try{const raw=storage.getItem(HANDOFF_KEY);storage.removeItem(HANDOFF_KEY);const value=raw&&JSON.parse(raw);if(value?.source==='events'&&Array.isArray(value.events))handoff=value;}catch{}return handoff;}

export const sampleSource={kind:'sample',label:'college life · demo data',timezone:'New York time',base:sampleBase,eventsFor:sampleEventsFor,reportFor:()=>null,meta:null};

export function priorityFor(stress){return stress>=7?3:stress>=4?2:1;}
export function calendarFor(type){return CALENDAR_FOR_TYPE[type]||'Me time';}
export function parseDate(iso){const [y,m,d]=iso.slice(0,10).split('-').map(Number);return new Date(y,m-1,d);}
export function mondayOf(date){const monday=new Date(date);monday.setDate(monday.getDate()-((monday.getDay()+6)%7));return monday;}
export function daysBetween(a,b){return Math.round((b-a)/DAY_MS);}
const addDays=(date,n)=>{const d=new Date(date);d.setDate(d.getDate()+n);return d;};
const isoDate=date=>`${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
// Wall-clock time in the calendar's own timezone, read straight from the ISO string.
const clockHours=iso=>Number(iso.slice(11,13))+Number(iso.slice(14,16))/60;

export function placeEvent(event){
 if(event.all_day)return {date:parseDate(event.start),start:ALL_DAY_AT,end:ALL_DAY_AT};
 let date=parseDate(event.start),start=clockHours(event.start);
 const end=daysBetween(date,parseDate(event.end))*24+clockHours(event.end);
 if(start<NIGHT_OWL_UNTIL){date=addDays(date,-1);return {date,start:start+24,end:end+24};}
 return {date,start,end};
}

// With no hell week, open on the busiest 7 days rather than an empty first week.
export function busiestWeekStart(days){let best=null,bestHours=0;for(let i=0;i<days.length;i++){const hours=days.slice(i,i+7).reduce((sum,d)=>sum+d.total_hours,0);if(hours>bestHours){best=days[i].date;bestHours=hours;}}return best;}

export function toHeatMapData(analysis){
 const {meta,days,events,prep_blocks:blocks,hell_weeks:hellWeeks}=analysis;
 const anchor=hellWeeks[0]?.key_events[0]?.date||hellWeeks[0]?.start||busiestWeekStart(days)||meta.start||events[0]?.start||isoDate(new Date());
 const base=mondayOf(parseDate(anchor));
 const stressOf=Object.fromEntries(events.map(e=>[e.id,e.stress]));
 const items=[
  ...events.map(e=>({...placeEvent(e),id:e.id,title:e.title,type:calendarFor(e.type),priority:priorityFor(e.stress),allDay:e.all_day})),
  ...blocks.map(b=>({date:parseDate(b.date),start:b.start_hour,end:b.end_hour,id:`prep:${b.event_id}:${b.date}:${b.start_hour}`,title:`Prep: ${b.title}`,type:'Classes',priority:priorityFor(stressOf[b.event_id]??7),prep:true})),
 ];
 const weeks=new Map();
 for(const {date,...item} of items){const offset=daysBetween(base,date),week=Math.floor(offset/7);if(!weeks.has(week))weeks.set(week,[]);weeks.get(week).push({...item,day:offset-week*7});}
 for(const list of weeks.values())list.sort((a,b)=>a.day-b.day||a.start-b.start);
 const reportFor=week=>{const first=isoDate(addDays(base,week*7)),last=isoDate(addDays(base,week*7+6));const hit=hellWeeks.find(h=>h.start<=last&&h.end>=first);return hit?{...hit,report:hit.report}:null;};
 return {
  kind:'live',
  label:`${meta.classifier==='gemma'?'Gemma':'keyword'} estimates · ${meta.start} to ${meta.end}`,
  timezone:meta.timezone.replace(/_/g,' '),
  base,
  eventsFor:week=>(weeks.get(week)||[]).map(e=>({...e})),
  reportFor,
  meta,
 };
}
