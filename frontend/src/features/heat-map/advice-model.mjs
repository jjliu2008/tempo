export const socialPresets={introvert:[],ambivert:['friends'],extrovert:['parties','clubs','friends']};
export const socialDefaults={style:'ambivert',likes:['parties','friends']};
export function interestOf(event){const title=event.title.toLowerCase();if(/party|night out/.test(title))return 'parties';if(/club|student org|soccer/.test(title))return 'clubs';if(/friends|roommates|dorm|brunch|dining hall/.test(title))return 'friends';return null;}
export function adviceFor(event,social=socialDefaults,custom=''){
 if(typeof custom==='string'&&custom.trim())return custom;
 const interest=interestOf(event),enjoyed=interest&&social.likes.includes(interest);
 if(enjoyed){if(interest==='parties')return 'Yeah! Party! This is your kind of night. 🎉';if(interest==='clubs')return 'Go find your people. This is your thing. ✨';return 'Your people, your plans. Go make a memory. 🫶';}
 if(interest){if(social.style==='introvert')return 'Not your scene? Skip it. A quiet night is a valid plan.';return 'Go if you feel like it. An early exit is always an option.';}
 if(event.type==='Me time')return /bed|sleep|netflix/i.test(event.title)?'Rest is part of the plan. Get comfy.':'A little reset? Absolutely. Make time for you.';
 return {1:'Just skip it. Protect your peace.',2:'Show up. Do your thing. Then log off.',3:'You gotta lock in. This one matters.'}[event.priority];
}
export function readSocial(storage){try{const value=JSON.parse(storage.getItem('tempo-social-v1'));return {style:Object.hasOwn(socialPresets,value?.style)?value.style:socialDefaults.style,likes:Array.isArray(value?.likes)?value.likes.filter(v=>['parties','clubs','friends'].includes(v)):[...socialDefaults.likes]};}catch{return {...socialDefaults,likes:[...socialDefaults.likes]};}}
