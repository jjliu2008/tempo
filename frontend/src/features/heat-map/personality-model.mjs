export const defaultMix={effort:'balanced',social:'balanced'};
export const effortLabels={lazy:'Lazy',balanced:'Balanced',grind:'Hardworking'};
export const socialLabels={introvert:'Introvert',balanced:'Ambivert',extrovert:'Extrovert'};
export function normalizeMix(value){if(typeof value==='string')return value==='extrovert'?{effort:'balanced',social:'extrovert'}:value==='lazy'?{effort:'lazy',social:'introvert'}:value==='grind'?{effort:'grind',social:'introvert'}:{...defaultMix};return {effort:Object.hasOwn(effortLabels,value?.effort)?value.effort:'balanced',social:Object.hasOwn(socialLabels,value?.social)?value.social:'balanced'};}
export function mixKey(value){const mix=normalizeMix(value);return `${mix.effort}-${mix.social}`;}
export function mixLabel(value){const mix=normalizeMix(value);return `${effortLabels[mix.effort]} + ${socialLabels[mix.social]}`;}
// What each setting means for the week, in words Gemma can act on. Shared by the remix and the hover advice.
const EFFORT_GOAL={
 lazy:'a genuinely lighter week: encourage skipping anything optional (importance 1 or 2) that is not needed, and never add anything',
 balanced:'keep the workload about as it is, skipping only what is clearly not worth it',
 grind:'a focused week: skip optional plans that compete with work, and lock in on everything that moves a deadline (about 6 hours of scheduled work on weekdays)',
};
const SOCIAL_GOAL={
 introvert:'protect quiet time alone and skip big social plans (parties, clubs)',
 balanced:'keep a healthy mix of social and alone time',
 extrovert:'make room for people: group study over solo study, and go to the social plans the student would enjoy',
};
export function mixGoal(value){const mix=normalizeMix(value);return `Work ethic: ${EFFORT_GOAL[mix.effort]}. Social energy: ${SOCIAL_GOAL[mix.social]}.`;}
// Rounded to quarter-minute precision so 0.1+0.2-style float noise never reaches the screen.
export function scheduledHours(events){return Number(events.reduce((sum,e)=>sum+e.end-e.start,0).toFixed(2));}
