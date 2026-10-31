const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const port=Number(process.argv[2]||8902);assert(port>=8900&&port<=8999&&port!==8767);
const output=process.env.WU_TRIGGER_EVIDENCE;if(output)fs.mkdirSync(output,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_BIN||'/usr/bin/google-chrome',args:['--no-sandbox']});
 const results=[];
 for(const width of [320,360,390,1440]){
  const page=await browser.newPage({viewport:{width,height:width===1440?1000:800}});const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',()=>errors.push('Native browser dialog'));
  await page.goto(`http://127.0.0.1:${port}/server/commands`);await page.getByRole('button',{name:'Open local test session'}).click();await page.getByRole('button',{name:/!lazy Used/}).waitFor();
  if(output)await page.screenshot({path:`${output}/${width}-list.png`,fullPage:true});
  await page.getByRole('button',{name:/!lazy Used/}).click();await page.locator('#command-reply-form').waitFor();
  assert.equal(await page.locator('body').evaluate(el=>el.scrollWidth<=innerWidth),true);
  const height=await page.locator('.text-commands').evaluate(el=>el.getBoundingClientRect().height);
  assert.equal(await page.locator('input[pattern^="!"]').evaluate(el=>{const old=el.value,readonly=el.readOnly;el.readOnly=false;el.value='!bad name';const invalid=el.validity.patternMismatch;el.value='!good-name';const valid=!el.validity.patternMismatch;el.value=old;el.readOnly=readonly;return invalid&&valid}),true);
  assert.equal(await page.locator('details').filter({has:page.locator('summary').filter({hasText:/^Reply ·/})}).getAttribute('open'),null);
  if(output)await page.screenshot({path:`${output}/${width}-editor.png`,fullPage:true});
  await page.locator('.command-danger summary').click();await page.getByRole('button',{name:'Delete !lazy',exact:true}).click();await page.getByRole('dialog').waitFor();
  assert.match(await page.getByRole('dialog').innerText(),/Its reply will be removed/);
  if(output)await page.screenshot({path:`${output}/${width}-danger.png`,fullPage:true});await page.getByRole('button',{name:'Cancel',exact:true}).click();
  const small=await page.locator('.text-commands').evaluate(el=>[...el.querySelectorAll('button,summary,small')].filter(n=>n.getClientRects().length&&!n.closest('details:not([open]) > :not(summary)')).map(n=>({text:n.textContent,size:parseFloat(getComputedStyle(n).fontSize),height:n.getBoundingClientRect().height,tag:n.tagName})).filter(n=>n.size<12||(n.tag!=='SMALL'&&n.height<43)));
  assert.deepEqual(small,[]);assert.deepEqual(errors,[]);results.push({width,height,screens:height/(width===1440?1000:800),errors});await page.close();
 }
 console.log(JSON.stringify(results,null,2));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
