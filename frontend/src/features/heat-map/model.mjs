export const defaults={capacity:6,importance:0};
export function dayTone(load){return load>=100?'hard':load>=60?'medium':'chill';}
export const toneLabels={chill:'Chill',medium:'Medium',hard:'Hard'};
export function topActivity(events){return [...events].sort((a,b)=>b.priority-a.priority||(b.end-b.start)-(a.end-a.start)||a.start-b.start)[0];}
export function loadHours(events){const ranges=events.map(e=>[e.start,e.end]).sort((a,b)=>a[0]-b[0]);let total=0,end=-Infinity;for(const [start,finish] of ranges){total+=Math.max(0,finish-Math.max(start,end));end=Math.max(end,finish);}return total;}
export function dailyLoad(events){return Math.round(loadHours(events)/defaults.capacity*100);}
export function classify(loads){const hellDays=loads.filter(n=>n>=100).length;return {hellDays,label:hellDays>=3?'Hell week':loads.some(n=>n>=60)?'Heating up':'Chill week'};}
export function intensity(events,hour){const occupied=loadHours(events.filter(e=>e.start<hour+1&&e.end>hour).map(e=>({...e,start:Math.max(hour,e.start),end:Math.min(hour+1,e.end)})));return occupied===0?0:Math.min(4,Math.max(1,Math.ceil(occupied*4)));}
