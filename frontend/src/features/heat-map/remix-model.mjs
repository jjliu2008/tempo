import {interestOf} from './advice-model.mjs';
export const remixLabels={extrovert:'Extrovert',lazy:'Soft life',grind:'Locked in'};
export function remixWeek(original,mode){
 if(!mode)return {events:original.map(e=>({...e})),changes:[]};
 const changes=[],events=[];
 for(const event of original){const e={...event},interest=interestOf(e);
  if(mode==='lazy'&&e.priority<3){changes.push({kind:'removed',id:e.id,title:e.title,day:e.day,detail:'Optional plan cleared for a genuinely lighter day'});continue;}
  if(mode==='grind'&&interest&&e.priority<3){changes.push({kind:'removed',id:e.id,title:e.title,day:e.day,detail:'Optional social plan cleared for focus'});continue;}
  if(mode==='extrovert'&&e.type==='Classes'&&/Library|readings/i.test(e.title)){e.title=/readings/i.test(e.title)?'Study group + coffee':'Library study crew';e.change='changed';changes.push({kind:'changed',id:e.id,title:e.title,day:e.day,detail:'Solo study → study with friends'});}
  if(mode==='extrovert'&&interest&&e.priority<3){e.priority=3;e.change='changed';changes.push({kind:'changed',id:e.id,title:e.title,day:e.day,detail:'Social plan → a personal priority'});}
  events.push(e);
 }
 const additions={extrovert:[[0,18.5,20,'Campus life','Dinner with new people',2],[2,18,19.5,'Campus life','Open mic with friends',2],[6,20.5,22,'Campus life','Dorm lounge hangout',2]],lazy:[[0,18,19,'Me time','Do nothing. On purpose.',1],[4,21,22,'Me time','Couch, snacks, zero plans',1],[5,21,22.5,'Me time','A night in > a night out',1]],grind:[[0,18.5,20.5,'Classes','Library deep-work block',3],[2,18,20,'Classes','Get ahead on assignments',3],[4,21,23,'Classes','Midterm practice sprint',3],[5,21,23,'Classes','Finish next week’s readings',3]]}[mode]||[];
 for(const [day,start,end,type,title,priority] of additions){if(events.some(e=>e.day===day&&e.start<end&&e.end>start))continue;if(mode==='lazy'&&scheduledHours(events.filter(e=>e.day===day))+end-start>3)continue;const id=`${original[0]?.id||'empty'}-remix-${mode}-${day}-${start}`,event={id,day,start,end,type,title,priority,change:'added'};events.push(event);changes.push({kind:'added',id,title,day,detail:mode==='lazy'?'A little protected recovery time':mode==='extrovert'?'More time with your people':'A protected focus session'});}
 return {events:events.sort((a,b)=>a.day-b.day||a.start-b.start),changes};
}
export function scheduledHours(events){return events.reduce((sum,e)=>sum+e.end-e.start,0);}
