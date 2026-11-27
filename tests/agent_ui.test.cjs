// Requires Playwright plus disposable capio_ui_test Postgres and Redis URLs.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {spawn, spawnSync} = require('node:child_process');
const {mkdtempSync, mkdirSync} = require('node:fs');
const {tmpdir} = require('node:os');
const path = require('node:path');
const {chromium} = require('playwright');

test('upload → review → feedback → reload → template → RQ render → result', {timeout:180000}, async () => {
  assert.match(process.env.DATABASE_URL || '', /\/capio_ui_test$/);
  const root=path.resolve(__dirname,'..'), dir=mkdtempSync(path.join(tmpdir(),'capio-agent-ui-'));
  for (const name of ['work','data','clips']) mkdirSync(path.join(dir,name));
  const env={...process.env,GEMINI_API_KEYS:'offline-test',LICENSE_KEY:'',AUTH_TOKEN:'',PYDANTIC_AI_NO_BANNER:'1',
    WORK_DIR:path.join(dir,'work'),DATA_DIR:path.join(dir,'data'),CLIPS_DIR:path.join(dir,'clips')};
  const python=process.env.CAPIO_PYTHON || path.join(root,'venv','Scripts','python.exe');
  const processes=[], logs=[];let browser;
  const start=mode=>{const p=spawn(python,['tests/agent_ui_runtime.py',mode],{cwd:root,env,windowsHide:true});processes.push(p);p.stdout.on('data',d=>logs.push(String(d)));p.stderr.on('data',d=>logs.push(String(d)));return p;};
  try {
    start('api');
    const base='http://127.0.0.1:18086';
    for(let i=0;i<60;i++){try{if((await fetch(base+'/agent')).ok)break;}catch{}await new Promise(r=>setTimeout(r,500));}
    start('worker');
    browser=await chromium.launch({channel:'chrome',headless:true});
    const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    const file=path.join(dir,'source.mp4');
    const ff=spawnSync('ffmpeg',['-y','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=24','-f','lavfi','-i','sine=frequency=440','-t','12','-c:v','libx264','-preset','ultrafast','-c:a','aac',file],{windowsHide:true});
    assert.equal(ff.status,0,String(ff.stderr));
    await page.route('**/api/agent/sessions',async route=>{
      if(route.request().method()!=='GET')return route.continue();
      const response=await route.fetch(), rows=await response.json();
      await route.fulfill({response,json:[...rows,{id:'00000000-0000-0000-0000-000000000001',brief:'Judul video yang sangat panjang '.repeat(12),status:'ready'}]});
    });
    await page.goto(base);await page.getByRole('link',{name:'Agent · Eksperimen'}).click();
    await page.locator('#agent-kind').selectOption('upload');
    await page.locator('#agent-file').setInputFiles(file);
    await page.waitForFunction(()=>document.querySelector('#agent-upload-status').textContent.includes('siap'));
    assert.equal(await page.locator('#agent-brief,#agent-count').count(),0);
    await page.getByRole('button',{name:'Siapkan video'}).click();
    await page.locator('#agent-state').filter({hasText:'Siap ditinjau'}).waitFor({timeout:60000});
    const sessionUrl=page.url();
    assert.equal(await page.locator('#agent-next').isVisible(),true);
    assert.equal(await page.locator('#agent-progress').isVisible(),false);
    const longTitle=page.locator('[data-session="00000000-0000-0000-0000-000000000001"]');
    assert.ok((await longTitle.boundingBox()).height<=70);
    assert.equal(await page.locator('#agent-list').evaluate(el=>el.scrollWidth<=el.clientWidth),true);
    assert.equal(await page.locator('.agent-candidate').count(),0);
    await page.locator('#agent-feedback').fill('Tonjolkan kemudahan produk untuk pemula.');
    await page.locator('#agent-send').click();
    await page.locator('.agent-candidate').first().waitFor({timeout:60000});
    await page.locator('[data-angle]').last().click();
    assert.match(await page.locator('#agent-feedback').inputValue(),/Pelajaran untuk pemula/);
    await page.locator('#agent-feedback').fill('');
    await page.getByRole('button',{name:'Pertahankan',exact:true}).first().click();
    await page.locator('.agent-candidate[data-decision=kept]').waitFor();
    await page.locator('#agent-feedback').fill('Cari alternatif lain.');
    await page.locator('#agent-send').click();
    await page.waitForFunction(()=>document.querySelectorAll('.agent-candidate').length===2,{},{timeout:60000});
    await page.reload();await page.locator('.agent-candidate[data-decision=kept]').waitFor({state:'attached'});
    assert.equal(await page.locator('#agent-review').isVisible(),false);
    await page.locator('#agent-review-toggle').click();
    assert.equal(await page.locator('.agent-candidate').count(),2);
    await page.getByRole('button',{name:'Putar',exact:true}).first().click();
    await page.waitForFunction(()=>document.querySelector('#agent-video').currentTime>0);
    await page.screenshot({path:path.join(dir,'agent-review.png'),fullPage:true});
    await page.getByRole('button',{name:'Putar konteks',exact:true}).first().click();
    await page.getByRole('button',{name:'Pertahankan',exact:true}).nth(1).click();
    await page.waitForFunction(()=>document.querySelectorAll('.agent-candidate[data-decision=kept]').length===2);
    await page.locator('[data-render]').first().uncheck();
    assert.match(await page.locator('#agent-render').textContent(),/Render 1 pilihan/);
    await page.locator('#agent-review-close').click();
    for(const viewport of [{width:1440,height:900},{width:1024,height:768},{width:390,height:844}]){
      await page.setViewportSize(viewport);
      await page.locator('#agent-feedback').fill('Draft tetap tersimpan');
      await page.waitForTimeout(2800);
      assert.equal(await page.locator('#agent-feedback').inputValue(),'Draft tetap tersimpan');
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
      const box=await page.locator('#agent-send').boundingBox();assert.ok(box.y+box.height<=viewport.height);
      await page.locator('#agent-review-toggle').click();
      await page.screenshot({path:path.join(dir,`agent-layout-${viewport.width}.png`)});
      await page.keyboard.press('Escape');assert.equal(await page.locator('#agent-review').isVisible(),false);
    }
    await page.locator('#agent-side-toggle').click();
    await page.keyboard.press('Escape');assert.equal(await page.locator('#agent-sidebar').isVisible(),false);
    await page.setViewportSize({width:1440,height:900});
    await page.locator('#agent-feedback').fill('baris satu');await page.locator('#agent-feedback').press('Shift+Enter');
    assert.match(await page.locator('#agent-feedback').inputValue(),/\n/);
    await page.locator('#agent-review-toggle').click();
    await page.locator('#agent-tab-source').click();assert.equal(await page.locator('#agent-knowledge').isVisible(),true);
    await page.locator('#agent-tab-candidates').click();
    await page.locator('#agent-render').click();
    await page.locator('#templates [data-id=mentahan]').click();
    await page.locator('#go:not([disabled])').waitFor();
    await page.locator('#go').click();await page.waitForURL('**/process#*');
    const jid=new URL(page.url()).hash.slice(1);
    let job;
    for(let i=0;i<100;i++){job=await(await fetch(base+'/jobs/'+jid)).json();if(['done','failed'].includes(job.status))break;await new Promise(r=>setTimeout(r,500));}
    assert.equal(job.status,'done',job.error);assert.equal(job.clips.length,1);
    assert.equal((await fetch(base+job.clips[0].url)).status,200);
    await page.goto(base+'/results#'+jid);await page.locator('.clip').first().waitFor();
    assert.equal(await page.getByText('Pilihan editor · Agent',{exact:true}).count(),1);
    await page.screenshot({path:path.join(dir,'agent-result.png'),fullPage:true});
    await page.goto(sessionUrl);await page.locator('#agent-renders a').first().waitFor();
    const fixture=await(await fetch(base+'/api/agent/sessions/'+new URL(sessionUrl).hash.slice(1))).json();
    const fid='00000000-0000-0000-0000-000000000002';
    let state={...fixture,id:fid,source_title:'Video dengan judul panjang '.repeat(8),status:'preparing',source_ready:false,progress:'Mentranskripsikan sumber',messages:[],candidates:[],renders:[]};
    await page.route('**/api/agent/sessions/'+fid,route=>route.fulfill({json:state}));
    await page.goto(base+'/agent#'+fid);
    await page.locator('#agent-progress').waitFor();
    assert.equal(await page.locator('#agent-chat').isVisible(),false);
    assert.match(await page.locator('#agent-progress-title').textContent(),/Menyiapkan videomu/);
    await page.locator('#agent-progress-details summary').click();
    assert.equal(await page.locator('#agent-steps [data-stage=current]').textContent(),'2Membuat transkrip');
    await page.screenshot({path:path.join(dir,'agent-preparing.png')});
    assert.equal(await page.locator('#agent-progress').evaluate(el=>!!(document.querySelector('#agent-messages').compareDocumentPosition(el)&Node.DOCUMENT_POSITION_FOLLOWING)),true);
    state={...state,status:'ready',source_ready:true,progress:'Siap ditinjau'};
    await page.locator('#agent-next').waitFor({timeout:10000});
    assert.equal(await page.locator('#agent-chat').isVisible(),true);
    assert.equal(await page.locator('#agent-progress').isVisible(),false);
    assert.deepEqual(errors,[]);
    console.log('Browser artifacts:',dir);
  } catch(error) {console.error(logs.join('').slice(-6000));throw error;}
  finally {if(browser)await browser.close();for(const p of processes)p.kill();}
});
