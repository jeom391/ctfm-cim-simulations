import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createDraftSaver} from '../src/lib/workflows.ts';

function deferred(){let resolve:(value:number)=>void=()=>{};const promise=new Promise<number>(r=>{resolve=r;});return {promise,resolve};}

test('overlapping A save, B waiter and C edit persist C with the returned version',async()=>{
 const a=deferred(),c=deferred(),sent:{value:string;expected_version:number}[]=[];
 let edit={token:1,value:'A'},version=1,dirty=true;
 const saver=createDraftSaver(
  ()=>dirty?{token:edit.token,value:{value:edit.value,expected_version:version}}:null,
  payload=>{sent.push(payload);return sent.length===1?a.promise:c.promise;},
  (savedVersion,token)=>{version=savedVersion;if(edit.token===token)dirty=false;}
 );
 const first=saver.flush();
 assert.deepEqual(sent,[{value:'A',expected_version:1}]);
 edit={token:2,value:'B'};
 const waiting=saver.flush();
 edit={token:3,value:'C'};
 a.resolve(2);
 await new Promise(resolve=>setImmediate(resolve));
 assert.deepEqual(sent,[{value:'A',expected_version:1},{value:'C',expected_version:2}]);
 assert.equal(dirty,true);
 c.resolve(3);
 await Promise.all([first,waiting]);
 assert.equal(dirty,false);assert.equal(version,3);
});
