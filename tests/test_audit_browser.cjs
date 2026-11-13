const {test}=require('node:test');
const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const {readFileSync,mkdirSync}=require('node:fs');
const {chromium}=require('playwright');
test('audit: status failures and exact UTF-8 source round trip', {timeout:100000},async()=>{
 const server=spawn('python3',['-m','http.server','8766','--bind','127.0.0.1'],{stdio:'ignore'});
 let browser;
 try {
  for(let i=0;i<60;i++){try{if((await fetch('http://127.0.0.1:8766')).ok)break;}catch{} await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const baseline={schema_version:1,mode:'build',luna_sha:'a'.repeat(40),tester_sha:'b'.repeat(40),compatible:true,checked_at:new Date().toISOString()};
  let build=baseline,live={...baseline,mode:'live'};
  await page.route('**/compatibility-build.json',route=>route.fulfill({json:build}));
  await page.route('https://raw.githubusercontent.com/**',route=>route.fulfill({json:live}));
  const cases=[
   ['matches',{}, {},'LUNA API SOURCE BASELINE MATCHES'],
   ['failed',{}, {compatible:false},'LUNA API DRIFT DETECTED'],
   ['stale',{}, {checked_at:'2020-01-01T00:00:00Z'},'LUNA API CHECK STALE'],
   ['mismatch',{}, {tester_sha:'c'.repeat(40)},'LUNA API CHECK UNVERIFIED'],
   ['malformed',{}, {luna_sha:'short'},'LUNA API STATUS UNAVAILABLE'],
   ['bad build',{compatible:false}, {},'LUNA API STATUS UNKNOWN'],
  ];
  for(const [name,b,l,label] of cases){
   build={...baseline,...b};live={...baseline,mode:'live',...l};
   await page.goto('http://127.0.0.1:8766');
   await page.waitForFunction(text=>document.querySelector('#compatibility-label').textContent===text,label);
  }
  await page.waitForFunction(()=>document.querySelector('#engine-status').textContent.includes('Python runtime ready'));
  const source='# café 🚀\nimport time\nif True:\n\tprint("héllo")\n\twait_for(1*ms)\n';
  await page.locator('#file-input').setInputFiles({name:'unicode-tabs.py',mimeType:'text/x-python',buffer:Buffer.from(source)});
  assert.equal(await page.locator('#source').inputValue(),source);
  await page.reload();
  await page.waitForFunction(()=>document.querySelector('#engine-status').textContent.includes('Python runtime ready'));
  assert.equal(await page.locator('#source').inputValue(),source);
  const downloadPromise=page.waitForEvent('download');
  await page.locator('#download').click();
  const download=await downloadPromise;
  assert.equal(readFileSync(await download.path(),'utf8'),source);
  await page.locator('#simulate').click();
  await page.waitForFunction(()=>document.querySelector('[data-check="runtime"]').dataset.state==='pass');
  assert.match(await page.locator('#diagnostics').textContent(),/btoa/);
  assert.equal(await page.locator('[data-check="api"]').getAttribute('data-state'),'partial');
  assert.ok((await page.locator('#highlight').textContent()).includes('héllo'));
  mkdirSync('reports/browser',{recursive:true});
  await page.screenshot({path:'reports/browser/audit-unicode-warning.png',fullPage:true});
  // Demonstrate upstream GUI transport independently, without server requests.
  const transport=await page.evaluate(()=>{
   const result={ascii:btoa('# ASCII\n')};
   for(const [name,text] of [['latin','# café'],['unicode','# 🚀']]){
    try{const bytes=Uint8Array.from(atob(btoa(text)),x=>x.charCodeAt(0));new TextDecoder('utf-8',{fatal:true}).decode(bytes);result[name]='accepted';}
    catch(e){result[name]=e.name;}
   }return result;
  });
  assert.equal(transport.latin,'TypeError');assert.equal(transport.unicode,'InvalidCharacterError');
 }finally{if(browser)await browser.close();server.kill();}
});
