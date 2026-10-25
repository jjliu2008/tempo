import {activityKind} from './activity-kind.mjs';
import {loadHours} from './model.mjs';
import {buildStressTimeline,surfaceStress} from './stress-model.mjs';
export const defaultCamera={yaw:-.56,pitch:.85,zoom:1,exaggeration:1.4};
export function terrainSample(events,day,hour){const stress=surfaceStress(buildStressTimeline(events),day,hour);return {height:.035+stress/100*3.8,stress};}
export function terrainColor(sample,shade=1){const height=sample.height??(.035+(sample.stress||0)/100*3.8),stops=[[0,[85,157,95]],[.7,[140,183,93]],[1.25,[229,203,100]],[1.8,[224,119,70]],[2.3,[210,65,56]],[3.2,[174,37,51]],[4,[151,32,55]]],h=Math.max(0,Math.min(4,height));for(let i=1;i<stops.length;i++)if(h<=stops[i][0]){const a=stops[i-1],b=stops[i],t=(h-a[0])/(b[0]-a[0]);return a[1].map((value,j)=>Math.max(0,Math.min(255,Math.round((value+(b[1][j]-value)*t)*shade))));}return stops.at(-1)[1];}
export function projectPoint(point,camera){const c=Math.cos(camera.yaw),s=Math.sin(camera.yaw),x=point.x*c-point.y*s,y=point.x*s+point.y*c,up=point.z*Math.cos(camera.pitch)-y*Math.sin(camera.pitch),depth=point.z*Math.sin(camera.pitch)+y*Math.cos(camera.pitch),perspective=22/(22-depth);return {x:x*perspective,y:-up*perspective,depth};}
export function worldPoint(day,hour,height){return {x:(day-3.5)*1.4,y:(hour-18)*.36,z:height};}
export function dayKindHours(events,day){return Object.fromEntries(['work','fun'].map(kind=>[kind,loadHours(events.filter(e=>e.day===day&&activityKind(e)===kind))]));}
export function barycentric(point,a,b,c){const denominator=(b.y-c.y)*(a.x-c.x)+(c.x-b.x)*(a.y-c.y);if(Math.abs(denominator)<.00001)return null;const u=((b.y-c.y)*(point.x-c.x)+(c.x-b.x)*(point.y-c.y))/denominator,v=((c.y-a.y)*(point.x-c.x)+(a.x-c.x)*(point.y-c.y))/denominator,w=1-u-v;return u>=-.001&&v>=-.001&&w>=-.001?[u,v,w]:null;}
