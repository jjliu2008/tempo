export const calendars=[{name:'Classes',color:'#a82732'},{name:'Campus life',color:'#e4766d'},{name:'Me time',color:'#bc8f8e'}];
export const days=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
export const base=new Date(2026,9,19);
export function dateAt(week,day){const date=new Date(base);date.setDate(date.getDate()+week*7+day);return date;}
// Fictional student timetable. Priorities are personal choices and can be edited.
const schedule=[
 [[8,9,'Classes','The dreaded 8am',1],[10,11.5,'Classes','Calculus lecture',2],[12,13,'Campus life','Dining hall with friends',1],[14,16,'Classes','Midterm study sprint',3],[17,18,'Campus life','Film club',2],[21,22.5,'Me time','Bed rotting & Netflix',1]],
 [[9,10,'Classes','Gen-ed: attendance optional',1],[10.5,12.5,'Classes','Chem lab',3],[13,14,'Campus life','Coffee with the roommates',1],[15,16.5,'Classes','Group project meetup',2],[18,19.5,'Campus life','Intramural soccer',2],[21,23,'Classes','Problem set due at midnight',3]],
 [[8,9,'Classes','That one useless class',1],[10,11.5,'Classes','Calculus lecture',2],[13,15,'Classes','Library lock-in',3],[16,17.5,'Campus life','Student org meeting',2],[20,22,'Campus life','Movie night in the dorm',1]],
 [[9,10,'Classes','Gen-ed: attendance optional',1],[11,12.5,'Classes','Chemistry lecture',3],[14,16,'Classes','Group presentation prep',3],[17,18,'Campus life','Photography club',2],[22,26,'Campus life','Thursday night out',1]],
 [[10,11,'Classes','Seminar that could be an email',1],[12,14,'Classes','Submit the big assignment',3],[15,16,'Me time','Gym & a brain reset',1],[18,19.5,'Campus life','Pizza with the roommates',1],[21,27,'Campus life','House party',1]],
 [[10,11.5,'Me time','Sleep in. Eventually brunch.',1],[13,15,'Classes','Catch up on readings',2],[16,18,'Campus life','Thrift run with friends',1],[21,27,'Campus life','The club afterparty',1]],
 [[10,11,'Me time','Laundry & life admin',1],[12,13.5,'Campus life','Brunch debrief',1],[15,17.5,'Classes','Sunday library reset',3],[19,20,'Me time','Meal prep & call home',2],[22,23,'Me time','Actually go to bed',1]],
];
export function eventsFor(week){return schedule.flatMap((entries,day)=>entries.map(([start,end,type,title,priority],index)=>({id:`college-${week}-${day}-${index}`,day,start,end,type,title,priority})));}
