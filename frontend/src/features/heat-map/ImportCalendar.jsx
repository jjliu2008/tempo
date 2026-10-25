import React,{useState} from 'react';
import {Upload,Link2,Sparkles,ArrowRight,Loader2} from 'lucide-react';
import {analysisApi,errorMessage} from '../../api/analysis';
import {toHeatMapData} from './live-data.mjs';

const SEMESTER={start:'2026-08-25',end:'2026-12-15'};

// Upload an .ics file or paste a secret iCal address. The address is a password:
// it lives only in this form's state, goes out in the POST body, and is cleared.
export default function ImportCalendar({onLoaded,busy,setBusy}){
 const [mode,setMode]=useState('file'),[file,setFile]=useState(null),[url,setUrl]=useState(''),[range,setRange]=useState(SEMESTER),[gemma,setGemma]=useState(true),[error,setError]=useState('');
 async function submit(e){
  e.preventDefault();setError('');
  const body={...range,gemma};
  if(mode==='file'){if(!file){setError('Choose an .ics file first.');return;}body.source='ics';body.ics=await file.text();}
  else{if(!url.trim()){setError('Paste your secret iCal address first.');return;}body.source='url';body.url=url.trim();}
  setBusy(gemma?'Gemma is reading your calendar… a first run takes about 30 seconds.':'Crunching your calendar…');
  try{onLoaded(toHeatMapData(await analysisApi.analyze(body)));setUrl('');}
  catch(err){setError(errorMessage(err));}
  finally{setBusy('');}
 }
 return <form className="import-calendar" onSubmit={submit}>
  <div className="import-tabs" role="tablist">
   <button type="button" role="tab" aria-selected={mode==='file'} className={mode==='file'?'selected':''} onClick={()=>setMode('file')}><Upload size={14}/> Upload .ics</button>
   <button type="button" role="tab" aria-selected={mode==='url'} className={mode==='url'?'selected':''} onClick={()=>setMode('url')}><Link2 size={14}/> Secret iCal link</button>
  </div>
  {mode==='file'
   ?<label className="import-field">Calendar file<input type="file" accept=".ics,text/calendar" onChange={e=>setFile(e.target.files?.[0]||null)}/><small>Google: Settings → Import &amp; export → Export. Apple: File → Export.</small></label>
   :<label className="import-field">Secret address in iCal format<input type="password" autoComplete="off" spellCheck={false} placeholder="https://calendar.google.com/calendar/ical/…/basic.ics" value={url} onChange={e=>setUrl(e.target.value)}/><small>Treat it like a password: anyone with it can read your whole calendar. It's used once and never saved. School accounts may hide it; export the .ics instead.</small></label>}
  <div className="import-range">
   <label className="import-field">From<input type="date" value={range.start} onChange={e=>setRange({...range,start:e.target.value})}/></label>
   <label className="import-field">To<input type="date" value={range.end} onChange={e=>setRange({...range,end:e.target.value})}/></label>
  </div>
  <label className="import-gemma"><input type="checkbox" checked={gemma} onChange={e=>setGemma(e.target.checked)}/><Sparkles size={14}/> Let Gemma estimate prep and write the forecast <small>(sends event titles only to Google)</small></label>
  {error&&<p className="import-error" role="alert">{error}</p>}
  <button className="button primary" type="submit" disabled={!!busy}>{busy?<><Loader2 size={16} className="spin"/> Working…</>:<>Find my hell weeks <ArrowRight size={16}/></>}</button>
 </form>;
}
