export const defaultMix={effort:'balanced',social:'balanced'};
export const effortLabels={lazy:'Lazy',balanced:'Balanced',grind:'Hardworking'};
export const socialLabels={introvert:'Introvert',balanced:'Ambivert',extrovert:'Extrovert'};
export function normalizeMix(value){if(typeof value==='string')return value==='extrovert'?{effort:'balanced',social:'extrovert'}:value==='lazy'?{effort:'lazy',social:'introvert'}:value==='grind'?{effort:'grind',social:'introvert'}:{...defaultMix};return {effort:Object.hasOwn(effortLabels,value?.effort)?value.effort:'balanced',social:Object.hasOwn(socialLabels,value?.social)?value.social:'balanced'};}
export function mixKey(value){const mix=normalizeMix(value);return `${mix.effort}-${mix.social}`;}
export function mixLabel(value){const mix=normalizeMix(value);return `${effortLabels[mix.effort]} + ${socialLabels[mix.social]}`;}
export function scheduledHours(events){return events.reduce((sum,e)=>sum+e.end-e.start,0);}
