const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const base='http://127.0.0.1:8903',out=process.env.WU_VISITOR_EVIDENCE;
assert(out);fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',args:['--no-sandbox']});
 try{
  const context=await browser.newContext({viewport:{width:360,height:800}});
  await context.route('**/*',r=>{const u=new URL(r.request().url());if(u.origin!==base)return r.abort();if(u.pathname.endsWith('/staff-overview'))return r.fulfill({json:{checked_at:Date.now()/1000,seasons:[],tickets:null,failures_count:0,failures:[],warnings:[],areas:[]}});return r.continue();});
  await context.request.get(base+'/qa/nav-role?role=owner');
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/staff');await page.getByRole('button',{name:'Open local test session'}).click();
  const section=page.locator('.visitor-summary');await section.getByText('Today',{exact:true}).waitFor();
  for(const width of [360,1440]){
   await page.setViewportSize({width,height:900});await section.scrollIntoViewIfNeeded();
   assert(await section.evaluate(el=>el.scrollWidth<=el.clientWidth));
   await page.screenshot({path:out+'/'+width+'-visitors.png',fullPage:true});
  }
  await section.getByText('Daily counts',{exact:true}).click();assert.equal(await section.locator('tbody tr').count(),30);
  await page.setViewportSize({width:360,height:900});assert(await section.evaluate(el=>el.scrollWidth<=el.clientWidth));
  await page.screenshot({path:out+'/360-daily-counts.png',fullPage:true});
  const response=await context.request.get(base+'/api/cwl/manage/visitors');assert.equal(response.status(),200);const payload=await response.json();assert(!JSON.stringify(payload).includes('user_id'));assert.deepEqual(errors,[]);
  fs.writeFileSync(out+'/browser.json',JSON.stringify({widths:[360,1440],dailyRows:30,aggregatesOnly:true,errors},null,2));console.log('Owner aggregate summary and30 daily rows verified at360/1440');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
