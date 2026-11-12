const fs = require('node:fs');
const {chromium} = require('../browser-tools/node_modules/playwright');
const out = '.cache/dashboard-display-20261112';
(async () => {
  const browser = await chromium.launch({headless:true});
  const page = await browser.newPage({viewport:{width:1440,height:1100}});
  const errors=[], failures=[];
  page.on('pageerror', e=>errors.push(String(e)));
  page.on('console', m=>{if(m.type()==='error') errors.push(m.text());});
  page.on('requestfailed', r=>failures.push(r.url()));
  const result={errors,failures};
  const check=(ok,message)=>{if(!ok) throw new Error(message);};
  try {
    await page.goto('http://127.0.0.1:8501',{waitUntil:'domcontentloaded'});
    await page.getByRole('heading',{name:'검색·추천 평가실',exact:true}).waitFor({timeout:120000});
    await page.getByText('시간은 KST(UTC+9)',{exact:false}).waitFor({timeout:120000});
    await page.getByRole('tab',{name:'A/B 실험',exact:true}).click();
    await page.getByText('Control CVR',{exact:true}).waitFor({timeout:120000});
    const metrics={};
    for (const label of ['Control CVR','Treatment CVR','CVR 상대 lift']) {
      metrics[label]=await page.locator('[data-testid="stMetric"]').filter({hasText:label}).innerText();
    }
    check(metrics['Control CVR'].includes('1.2%'),'control precision');
    check(metrics['Treatment CVR'].includes('0.9%'),'treatment precision');
    check(metrics['CVR 상대 lift'].includes('-27.7%'),'lift precision');
    const panel=page.locator('[role="tabpanel"]:visible');
    await page.getByText('양측 cluster Z p-value: 4.4e-106',{exact:true}).waitFor();
    const plot=panel.locator('.js-plotly-plot').first();
    await plot.waitFor();
    result.chart=await plot.evaluate(e=>({ticks:e._fullLayout.yaxis.tickformat,
      hover:e._fullLayout.yaxis.hoverformat,raw_cvr:e.data[0].y[1]}));
    check(result.chart.ticks==='.1%' && result.chart.hover==='.1%','chart formatting');
    check(Math.abs(result.chart.raw_cvr-0.012253333333333333)<1e-15,'chart raw value changed');
    result.metrics=metrics;
    await page.screenshot({path:out+'/ab.png',fullPage:true});
    await page.getByRole('tab',{name:'시스템',exact:true}).click();
    await page.getByRole('heading',{name:'CT 기록',exact:true}).scrollIntoViewIfNeeded();
    await page.screenshot({path:out+'/ct.png',fullPage:true});
    await page.getByRole('tab',{name:'EDA·구매 이력',exact:true}).click();
    await page.getByText('분석 시각=',{exact:false}).waitFor();
    result.audit=await page.getByText('분석 시각=',{exact:false}).innerText();
    const audit=JSON.parse(fs.readFileSync('docs/results/docker/runtime-v44/full/data_audit.json','utf8'));
    const kst=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',
      day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}).format(new Date(audit.generated_at))+' KST';
    check(result.audit.includes(kst),'audit timezone');
    await page.getByText('실제 구매 ',{exact:false}).scrollIntoViewIfNeeded();
    await page.screenshot({path:out+'/purchases.png',fullPage:true});
    await page.getByRole('tab',{name:'상품·CLIP',exact:true}).click();
    await page.getByRole('heading',{name:'상품 원천 데이터와 실제 CLIP 벡터',exact:true}).waitFor();
    result.catalog=await page.locator('[role="tabpanel"]:visible').innerText();
    check(result.catalog.includes('KST'),'catalog timezone');
    for (const name of ['검색','추천']) await page.getByRole('tab',{name,exact:true}).click();
    check(!(await page.locator('[data-testid="stException"]').count()),'Streamlit exception');
    check(!errors.length&&!failures.length,'browser errors');
    result.status='PASS';
  } catch(e) {result.status='FAIL';result.error=String(e);process.exitCode=1;
    await page.screenshot({path:out+'/failure.png',fullPage:true});
  } finally {fs.writeFileSync(out+'/browser.json',JSON.stringify(result,null,2)+'\n');
    console.log(JSON.stringify({status:result.status,error:result.error,errors,failures}));await browser.close();}
})();
