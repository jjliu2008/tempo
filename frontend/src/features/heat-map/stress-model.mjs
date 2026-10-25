import {activityKind} from './activity-kind.mjs';
import {loadHours} from './model.mjs';
// Illustrative UI simulation, not a measurement of the user's mental health.
const cache=new WeakMap();
export const stressSettings={step:.25,initial:12,workPerHour:22,funRecoveryPerHour:12,freeRecoveryPerHour:7,overnightRecoveryPerHour:10,overload:80};
export function stressState(stress){return stress>=80?'Overloaded':stress>=60?'High stress':stress>=35?'Building':'Low stress';}
export function buildStressTimeline(events){if(cache.has(events))return cache.get(events);const days=[];let stress=stressSettings.initial,streak=0;for(let day=0;day<7;day++){if(day){stress=Math.max(0,stress-4*stressSettings.overnightRecoveryPerHour);streak=0;}const points=[{day,hour:8,stress,trend:stress>0?'Settling':'Steady',work:0,fun:0}];for(let i=0;i<80;i++){const hour=8+i*.25,end=hour+.25,relevant=events.filter(e=>e.day===day&&e.start<end&&e.end>hour),occupied=kind=>loadHours(relevant.filter(e=>activityKind(e)===kind).map(e=>({...e,start:Math.max(hour,e.start),end:Math.min(end,e.end)}))),work=occupied('work'),fun=Math.min(.25-work,occupied('fun')),free=Math.max(0,.25-work-fun),before=stress;
 const gain=work*stressSettings.workPerHour*(1+Math.min(6,streak+work/2)*.1),recovery=fun*stressSettings.funRecoveryPerHour+free*stressSettings.freeRecoveryPerHour;
 stress=Math.max(0,Math.min(100,stress+gain-recovery));streak=work>0?Math.min(8,streak+work):Math.max(0,streak-(fun+free)*2);
 points.push({day,hour:end,stress,trend:stress>before+.01?'Building':stress<before-.01?'Recovering':'Steady',work,fun});}days.push(points);}
 const summaries=days.map(points=>({peak:Math.round(Math.max(...points.map(p=>p.stress))),overloadedHours:points.slice(1).filter(p=>p.stress>=stressSettings.overload).length*.25,end:Math.round(points.at(-1).stress)})),result={days,summaries};cache.set(events,result);return result;}
export function stressAt(timeline,day,hour){const index=Math.max(0,Math.min(80,(hour-8)*4)),lower=Math.floor(index),upper=Math.min(80,lower+1),fraction=index-lower,points=timeline.days[Math.max(0,Math.min(6,day))];return points[lower].stress*(1-fraction)+points[upper].stress*fraction;}
export function surfaceStress(timeline,day,hour){const x=Math.max(0,Math.min(6,day-.5)),left=Math.floor(x),right=Math.min(6,left+1),t=x-left,ease=t*t*(3-2*t);return stressAt(timeline,left,hour)*(1-ease)+stressAt(timeline,right,hour)*ease;}
