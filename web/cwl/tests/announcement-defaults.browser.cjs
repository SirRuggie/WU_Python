const {chromium}=require('playwright');const assert=require('node:assert/strict');
const port=Number(process.argv[2]);assert(port>=8900&&port<=8999);const base=`http://127.0.0.1:${port}`;
(async()=>{const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',args:['--no-sandbox']});try{
const context=await browser.newContext({viewport:{width:360,height:800}});await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());const page=await context.newPage();
await page.goto(base+'/?view=publication&step=announce&season=1');await page.getByRole('button',{name:'Open local test session'}).click();await page.locator('.announcement-pool-card').first().waitFor();
await page.getByText('Testing and images',{exact:true}).click();await page.getByText('Single-clan test',{exact:true}).click();
const single=page.locator('section.clan-roster-images');await single.getByRole('combobox',{name:'Test channel',exact:true}).waitFor();
await page.waitForFunction(() => [...document.querySelectorAll('section.clan-roster-images input')].some(e => e.value.includes('staff-tests')));
assert.match(await single.getByRole('combobox',{name:'Test channel',exact:true}).inputValue(),/staff-tests/);
await page.getByRole('button',{name:'Test all…',exact:true}).click();const all=page.getByRole('dialog',{name:'Test all roster images'});
await all.waitFor();await page.waitForFunction(() => [...document.querySelectorAll('dialog input')].some(e => e.value.includes('staff-tests')));assert.match(await all.getByRole('combobox',{name:'Test channel',exact:true}).inputValue(),/staff-tests/);
assert.equal(await all.getByLabel('Make this the default').isChecked(),false);
const before=await(await context.request.get(base+'/api/cwl/manage/announcement-test-channel')).json();
await all.getByRole('combobox',{name:'Test channel',exact:true}).fill('main-cwl');await all.getByRole('option').first().click();
await page.keyboard.press('Escape');const after=await(await context.request.get(base+'/api/cwl/manage/announcement-test-channel')).json();assert.deepEqual(after,before);
console.log('Single-clan and Test all preselection passed; cancelled override left default unchanged');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1);});
