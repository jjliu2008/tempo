export const activityKinds={work:{label:'Work',color:'#cc4553',symbol:'◆'},fun:{label:'Fun',color:'#4c9b64',symbol:'✦'}};
export function activityKind(event){return event.type==='Classes'||event.type==='Work'?'work':'fun';}
