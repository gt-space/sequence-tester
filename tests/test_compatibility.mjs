import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../src/compatibility.js',import.meta.url),'utf8');
const { validCompatibilityStatus: valid } = await import('data:text/javascript,'+encodeURIComponent(source));
const good = {schema_version:1,mode:'build',luna_sha:'a'.repeat(40),tester_sha:'b'.repeat(40),compatible:true,checked_at:new Date().toISOString()};
test('status requires full revisions, a successful baseline and valid timestamps',()=>{
 assert.equal(valid(good,'build'),true);
 for (const patch of [{compatible:false},{compatible:'true'},{luna_sha:'short'},{tester_sha:null},{checked_at:'invalid'},{mode:'live'}])
  assert.equal(valid({...good,...patch},'build'),false,JSON.stringify(patch));
 assert.equal(valid({...good,mode:'live',compatible:false},'live'),true);
});
