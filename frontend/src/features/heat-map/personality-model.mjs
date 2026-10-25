import {interestOf} from './advice-model.mjs';
export const defaultMix={effort:'balanced',social:'balanced'};
export const effortLabels={lazy:'Lazy',balanced:'Balanced',grind:'Hardworking'};
export const socialLabels={introvert:'Introvert',balanced:'Ambivert',extrovert:'Extrovert'};
export function normalizeMix(value){if(typeof value==='string')return value==='extrovert'?{effort:'balanced',social:'extrovert'}:value==='lazy'?{effort:'lazy',social:'introvert'}:value==='grind'?{effort:'grind',social:'introvert'}:{...defaultMix};return {effort:Object.hasOwn(effortLabels,value?.effort)?value.effort:'balanced',social:Object.hasOwn(socialLabels,value?.social)?value.social:'balanced'};}
export function mixKey(value){const mix=normalizeMix(value);return `${mix.effort}-${mix.social}`;}
export function mixLabel(value){const mix=normalizeMix(value);return `${effortLabels[mix.effort]} + ${socialLabels[mix.social]}`;}
export function scheduledHours(events){return events.reduce((sum,e)=>sum+e.end-e.start,0);}
export function remixWeek(original,configuration){
 if(!configuration)return {events:original.map(e=>({...e})),changes:[]};
 const mix=normalizeMix(configuration),key=mixKey(mix),events=[],changes=[];
 const remove=(e,detail)=>changes.push({kind:'removed',id:e.id,title:e.title,day:e.day,detail});
 for(const originalEvent of original){const e={...originalEvent},interest=interestOf(e),optional=e.priority<3;
  if(optional&&mix.effort==='lazy'){remove(e,'Optional plan cleared for a genuinely lighter day');continue;}
  if(optional&&mix.effort==='grind'&&(interest||(e.type==='Classes'&&e.priority===1))){remove(e,'Optional plan cleared for focused work');continue;}
  if(optional&&mix.social==='introvert'&&(interest==='parties'||interest==='clubs')){remove(e,'Big social plan cleared for quiet time');continue;}
  if(mix.social==='extrovert'&&e.type==='Classes'&&/Library|readings/i.test(e.title))e.title=/readings/i.test(e.title)?'Study group + coffee':'Library study crew';
  if(mix.social==='extrovert'&&interest&&mix.effort!=='lazy')e.priority=3;
  if(e.title!==originalEvent.title||e.priority!==originalEvent.priority){e.change='changed';changes.push({kind:'changed',id:e.id,title:e.title,day:e.day,detail:e.type==='Classes'?'Solo study → study with friends':'Social plan → a personal priority'});}
  events.push(e);
 }
 function add(day,start,end,type,title,priority,detail,softLimit=false){if(events.some(e=>e.day===day&&e.start<end&&e.end>start))return false;if(softLimit&&scheduledHours(events.filter(e=>e.day===day))+end-start>3)return false;const id=`${original[0]?.id||'empty'}-mix-${key}-${day}-${start}`,event={id,day,start,end,type,title,priority,change:'added'};events.push(event);changes.push({kind:'added',id,title,day,detail});return true;}
 if(mix.effort==='lazy'){
  const proposals=mix.social==='extrovert'?[[0,18,19,'Campus life','Dinner with new people',2],[4,21,22,'Campus life','One-hour party cameo',2],[5,21,22.5,'Campus life','Low-key hangout with friends',2]]:mix.social==='balanced'?[[0,18,19,'Me time','Do nothing. On purpose.',1],[4,21,22,'Me time','Couch, snacks, zero plans',1],[5,16,17.5,'Campus life','Coffee with a friend',2]]:[[0,18,19,'Me time','Do nothing. On purpose.',1],[4,21,22,'Me time','Couch, snacks, zero plans',1],[5,21,22.5,'Me time','A night in > a night out',1]];
  for(const p of proposals)add(...p,'A little of what recharges you',true);
 }else if(mix.social==='extrovert'){
  for(const p of [[0,18.5,20,'Campus life','Dinner with new people',2],[2,18,19.5,'Campus life','Open mic with friends',2],[6,20.5,22,'Campus life','Dorm lounge hangout',2]])add(...p,'More time with your people');
 }else if(mix.social==='introvert'&&mix.effort==='balanced'){
  for(const p of [[3,21,22,'Me time','Quiet night, fully intentional',1],[5,21,22.5,'Me time','Recharge without the crowd',1]])add(...p,'A little protected alone time');
 }
 if(mix.effort==='grind')for(let day=0;day<7;day++){
  const target=day<5?6.5:4;let block=0;
  for(let start=9;start<22&&scheduledHours(events.filter(e=>e.day===day))<target;start+=.5){const remaining=target-scheduledHours(events.filter(e=>e.day===day)),length=Math.min(1.5,Math.floor(remaining*2)/2);if(length<.5)break;const title=mix.social==='extrovert'?(block?'Assignment sprint with friends':'Library study crew'):(block?'Get ahead on assignments':'Library deep-work block');if(add(day,start,start+length,'Classes',title,3,'Protected study time, matched to your social energy'))block++;}
 }
 return {events:events.sort((a,b)=>a.day-b.day||a.start-b.start),changes};
}
