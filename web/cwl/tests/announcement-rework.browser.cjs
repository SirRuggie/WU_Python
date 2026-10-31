const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const base = 'http://127.0.0.1:8900';
const out = process.env.WU_SEQUENCE_EVIDENCE;
assert(out); fs.mkdirSync(out, {recursive:true});
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',args:['--no-sandbox']});
 try {
  const context=await browser.newContext({viewport:{width:360,height:800}});
  const calls=[]; let checks=0;
  await context.route('**/*', async route=>{
   const request=route.request(),url=new URL(request.url());
   if(url.origin!==base)return route.abort();
   if(url.pathname.endsWith('/check-message')) { checks++; return route.fulfill({json:{deleted:true,message_id:'555555555555555550'}}); }
   if(url.pathname.endsWith('/test-full')&&request.method()==='POST') {calls.push(request.postDataJSON());return route.fulfill({status:500,body:'Connection interrupted; outcome unknown'});}
   return route.continue();
  });
  const page=await context.newPage(); const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/?view=publication&step=announce&season=1');
  await page.getByRole('button',{name:'Open local test session'}).click();
  await page.getByText('Previous post was deleted', {exact:false}).first().waitFor();
  assert(checks>0);assert.equal(await page.locator('.announcement-send-review').count(),0);
  await page.screenshot({path:out+'/360-auto-deleted.png',fullPage:true});
  await page.getByRole('button',{name:'Edit',exact:true}).first().click();
  await page.getByText('Test full post · no pings',{exact:true}).click();
  const input=page.getByRole('combobox',{name:'Full test channel'});
  await input.fill('staff-tests');await page.getByRole('option',{name:'staff-tests',exact:false}).click();
  await page.getByRole('button',{name:'Test full post',exact:true}).click();
  await page.getByRole('button',{name:'Send full test',exact:true}).click();
  await page.waitForTimeout(500); assert.equal(calls.length,1);
  assert(await input.isDisabled());assert((await input.inputValue()).includes('staff-tests'));
  await page.getByRole('button',{name:'Test full post',exact:true}).click();
  assert((await page.locator('.confirm-dialog').textContent()).includes('#staff-tests'));
  await page.screenshot({path:out+'/360-test-retry-channel.png',fullPage:true});
  await page.getByRole('button',{name:'Send full test',exact:true}).click();
  await page.waitForTimeout(300);assert.equal(calls.length,2);assert.deepEqual(calls[0],calls[1]);assert.deepEqual(errors,[]);
  fs.writeFileSync(out+'/rework-browser.json',JSON.stringify({automaticChecks:checks,retryBodiesIdentical:true,lockedChannel:true,errors},null,2));
  console.log('Deleted detection and locked exact-body retry passed; fake responses only');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1)});
