import {test} from 'node:test';
import assert from 'node:assert/strict';
import {request,ApiError} from '../src/lib/api/index.ts';

test('stale comparison versions expose HTTP 409 so the UI can reload the server draft',async()=>{
 const original=globalThis.fetch;
 globalThis.fetch=async()=>new Response(JSON.stringify({error:{code:'http_error',message:'Draft changed',request_id:'r'}}),{status:409,headers:{'Content-Type':'application/json'}});
 try{await assert.rejects(request('/comparisons/one'),(error:unknown)=>error instanceof ApiError&&error.status===409&&error.requestId==='r');}
 finally{globalThis.fetch=original;}
});
