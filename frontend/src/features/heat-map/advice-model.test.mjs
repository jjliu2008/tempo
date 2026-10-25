import test from 'node:test';
import assert from 'node:assert/strict';
import {adviceFor,readSocial,socialPresets} from './advice-model.mjs';
const party={title:'House party',type:'Campus life',priority:1};
test('extroverts get positive party advice even for low priority social events',()=>{assert.match(adviceFor(party,{style:'extrovert',likes:socialPresets.extrovert}),/Yeah! Party!/);});
test('interests can override social style and custom messages take precedence',()=>{assert.match(adviceFor(party,{style:'introvert',likes:['parties']}),/Yeah! Party!/);assert.match(adviceFor(party,{style:'introvert',likes:[]}),/quiet night/);assert.equal(adviceFor(party,{style:'extrovert',likes:['parties']},'Go dance!'),'Go dance!');});
test('academic priorities remain meaningful and rest is encouraged',()=>{assert.match(adviceFor({title:'That useless class',type:'Classes',priority:1}),/skip it/);assert.match(adviceFor({title:'Midterm',type:'Classes',priority:3}),/lock in/);assert.match(adviceFor({title:'Sleep in',type:'Me time',priority:1}),/Rest/);});
test('saved social preferences recover safely from invalid storage',()=>{assert.deepEqual(readSocial({getItem:()=>JSON.stringify({style:'extrovert',likes:['parties','unknown']})}),{style:'extrovert',likes:['parties']});assert.equal(readSocial({getItem:()=>'{bad'}).style,'ambivert');});
