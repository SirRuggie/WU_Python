const {chromium}=require('playwright');
const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
const out=path.resolve(__dirname,'../../../.local/p93-layout');fs.mkdirSync(out,{recursive:true});
const port=fs.readFileSync(path.resolve(__dirname,'../../../.local/p93-preview-port'),'utf8').trim();const origin='http://127.0.0.1:'+port;
(async()=>{const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});const evidence=[];
try{for(const width of [320,360,390,1440]){const page=await browser.newPage({viewport:{width,height:1000}});const errors=[];page.on('pageerror',error=>errors.push(error.message));await page.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());await page.goto(origin+'/server/members');const login=page.getByRole('button',{name:/Open local test session/i});await login.waitFor();await login.click();await page.locator('.members-workspace h1').waitFor();await page.locator('.members-person').first().waitFor();
assert.equal(await page.locator('.members-person').count(),25);assert.equal(await page.locator('.members-person input:disabled').count(),0);
assert(await page.getByText(/Showing 1-25 of 1,4/).isVisible());assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
await page.screenshot({path:path.join(out,'overview-'+width+'.png'),fullPage:true});
await page.locator('.members-person-open').first().click();await page.getByRole('button',{name:'Back to members',exact:true}).waitFor();
assert(await page.getByRole('link',{name:'Moderation history',exact:true}).isVisible());
assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
await page.screenshot({path:path.join(out,'person-'+width+'.png'),fullPage:true});
await page.getByRole('button',{name:'Back to members',exact:true}).click();await page.waitForTimeout(150);assert.equal(await page.locator('.members-person').count(),25);
assert.deepEqual(errors,[]);evidence.push({width,rows:25,noOverflow:true,back:true,errors});await page.close();}
fs.writeFileSync(path.join(out,'initial-results.json'),JSON.stringify(evidence,null,2));console.log('Four full-app Members overview/person/Back cases pass');}
finally{await browser.close();}})().catch(error=>{console.error(error);process.exit(1)});
