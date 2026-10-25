import React from 'react';
import {Leaf,Zap,Users,Headphones,Sparkles,Loader2} from 'lucide-react';
import {defaultMix,effortLabels,socialLabels} from './personality-model.mjs';

// Picking only edits a draft. Gemma runs when the student presses Remix or Enter.
// Clicking the selected option again clears it back to the middle.
function Axis({number,title,left,right,name,options,current,onPick,label,hint}){
 return <fieldset className="personality-axis"><legend><span className="axis-number">{number}</span> {title}</legend><div className="axis-endpoints">{left}{right}</div><div className="axis-options" role="radiogroup" aria-label={label}>{Object.entries(options).map(([id,text])=><button type="button" role="radio" aria-checked={current===id} key={id} className={current===id?'selected':''} onClick={()=>onPick(current===id&&id!=='balanced'?'balanced':id)}>{text}</button>)}</div><p>{hint}</p></fieldset>;
}

export default function PersonalityControls({value=defaultMix,onChange,onApply,canApply=false,busy='',active=false,context='calendar'}){
 const apply=()=>{if(canApply&&!busy)onApply();};
 return <div className="personality-controls" onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();apply();}}}>
  <Axis number="01" title="How much are we doing?" left={<span><Leaf size={15}/> Laziness</span>} right={<span>Hard work <Zap size={15}/></span>} options={effortLabels} current={value.effort} onPick={effort=>onChange({...value,effort})} label={`${context} effort level`} hint={value.effort==='lazy'?'Skip what you can. Nothing gets added, and optional plans go.':value.effort==='grind'?'More study time. Clear distractions and protect focus blocks.':'Keep a fuller mix of classes, life, and downtime.'}/>
  <Axis number="02" title="Where do you recharge?" left={<span><Headphones size={15}/> Introvert</span>} right={<span>Extrovert <Users size={15}/></span>} options={socialLabels} current={value.social} onPick={social=>onChange({...value,social})} label={`${context} social energy`} hint={value.social==='introvert'?'Trade optional crowds for quiet time. Work can stay solo.':value.social==='extrovert'?'Make room for people. Even study time can be social.':'A little company, a little space. Best of both.'}/>
  <div className="axis-footnote"><span>Mix independently. Lazy + extrovert is a whole vibe.</span><strong>{busy?'Gemma is remixing…':canApply?'Press Enter or Remix to apply':active?'Your combination is applied':'Choose both controls, then press Remix'}</strong><button type="button" className="remix-apply" disabled={!canApply||Boolean(busy)} onClick={apply}>{busy?<Loader2 size={14} className="spin"/>:<Sparkles size={14}/>} Remix</button></div>
 </div>;
}
