import test from 'node:test';
import assert from 'node:assert/strict';
import {readSocial,interestOf} from './advice-model.mjs';

test('saved social preferences recover safely from invalid storage',()=>{assert.deepEqual(readSocial({getItem:()=>JSON.stringify({style:'extrovert',likes:['parties','unknown']})}),{style:'extrovert',likes:['parties']});assert.equal(readSocial({getItem:()=>'not json'}).style,'ambivert');});
test('social interests come from the event title',()=>{assert.equal(interestOf({title:'House party'}),'parties');assert.equal(interestOf({title:'Photography club'}),'clubs');assert.equal(interestOf({title:'CHEM Midterm'}),null);});
