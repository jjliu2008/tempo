// The fictional demo semesters /schedule?demo=<id> can open. ids match the backend's
// `demo` field (backend/hellweek/make_demo.py DEMO_VARIANTS).
export const DEMO_ACCOUNTS=[
 {id:'engineering',name:'Engineering crunch',blurb:'Two midterms and a project due within 48 hours.'},
 {id:'social-crunch',name:'Busy and social',blurb:'The same crunch, with a full social calendar pulling at it.'},
 {id:'work-crunch',name:'Busy and working',blurb:'Bookstore and cafe shifts, then three midterms in a row.'},
 {id:'humanities',name:'Reading and writing heavy',blurb:'Papers, an oral exam and moot court. No labs.'},
];
// `?demo` alone, or an unknown id, opens the first one.
export function demoFromSearch(search){const value=new URLSearchParams(search).get('demo');return value===null?null:(DEMO_ACCOUNTS.find(d=>d.id===value)||DEMO_ACCOUNTS[0]).id;}
