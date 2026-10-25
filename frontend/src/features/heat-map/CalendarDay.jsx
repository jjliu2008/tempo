import React from 'react';
import {Flame} from 'lucide-react';
import {topActivity,dayTone,toneLabels} from './model.mjs';
export default function CalendarDay({day,date,load,events,onSelect}){const top=topActivity(events),tone=dayTone(load);return <div className={`day-heading tone-${tone} ${load>=100?'hell-day':''}`}><span>{day.slice(0,3)}</span><strong>{date}</strong><small>{load>=100&&<Flame size={12}/>} {toneLabels[tone]} · {load}%</small>{top?<button className="day-highlight" title={top.title} aria-label={`Most important on ${day}: ${top.title}`} onClick={()=>onSelect(Math.floor(top.start))}><span>✦ TOP PRIORITY</span><strong>{top.title}</strong></button>:<div className="day-highlight empty-highlight"><span>NOTHING PLANNED</span><strong>All yours.</strong></div>}</div>;}
