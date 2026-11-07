/* Actual Chromium UI check. Set PLAYWRIGHT_MODULE to an installed Playwright package. */
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async () => {
  const out = process.env.BROWSER_RESULTS || 'docs/results/integration/20261107_requirements';
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch({headless: true});
  const page = await browser.newPage({viewport: {width: 1440, height: 1100}});
  const errors = [], failedRequests = [], captures = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('requestfailed', r => failedRequests.push({url: r.url(), error: r.failure()}));
  const report = {started_at: new Date().toISOString(), browser: browser.version(), errors, failedRequests, captures, checks: {}};
  async function shot(name) {
    if (await page.locator('[data-testid="stException"]').count()) throw new Error('Streamlit exception rendered');
    const target = path.join(out, `browser_${name}.png`);
    await page.screenshot({path: target, fullPage: true}); captures.push(target);
  }
  async function settled() {
    await page.locator('[data-testid="stStatusWidget"]').waitFor({state: 'hidden', timeout: 120000});
  }
  try {
    await page.goto(process.env.DASHBOARD_URL || 'http://localhost:8501', {waitUntil: 'domcontentloaded'});
    await page.getByRole('heading', {name: '검색·추천 평가실', exact: true}).waitFor({timeout: 120000});
    await settled();
    const docsUrl = await page.getByRole('link', {name: 'API 문서 열기', exact: true}).getAttribute('href');
    const docsResponse = await page.request.get(docsUrl);
    report.api_docs = {url: docsUrl, status: docsResponse.status()};
    report.checks.api_docs_link = docsResponse.status() === 200;
    if (!report.checks.api_docs_link) throw new Error('public API documentation link is unavailable');
    const names = ['검색','추천','A/B 실험','시스템','EDA·구매 이력','상품·CLIP'];
    for (const [index, name] of names.entries()) {
      await page.getByRole('tab', {name, exact: true}).click(); await settled(); await shot(`tab_${index}`);
      report.checks[`tab_${name}`] = true;
      const content = await page.locator('[role="tabpanel"]:visible').innerText();
      if (/EDA 읽기 실패|상품·CLIP 조회 실패|배포 데이터 확인 실패/.test(content)) throw new Error(content);
      if (index === 4) {
        await page.getByRole('textbox', {name: '구매 원장 사용자 ID', exact: true}).scrollIntoViewIfNeeded();
        await shot('purchase_ledger');
      }
      if (index === 5) {
        await page.getByText('item_ids.json의 실제 행과', {exact: false}).scrollIntoViewIfNeeded();
        await shot('clip_vectors');
      }
    }
    await page.getByRole('tab', {name: '검색', exact: true}).click();
    await page.getByRole('textbox', {name: '검색어', exact: true}).fill('검정 오버핏 후드티');
    await page.getByRole('button', {name: '검색 실행', exact: true}).click();
    await page.locator('[role="tabpanel"]:visible img').first().waitFor({timeout: 120000}); await settled();
    report.checks.search_images = await page.locator('[role="tabpanel"]:visible img').count() > 0;
    await shot('search');
    await page.getByRole('tab', {name: '추천', exact: true}).click();
    await page.getByRole('textbox', {name: '사용자 ID', exact: true}).fill('browser-' + Date.now());
    await page.getByRole('button', {name: '추천 실행', exact: true}).click();
    const click = page.getByRole('button', {name: '이 상품 클릭 후 추천 비교', exact: true}).first();
    await click.waitFor({timeout: 120000}); await settled(); await shot('recommend');
    await click.click();
    await page.getByRole('heading', {name: '실제 클릭 전후 비교', exact: true}).waitFor({timeout: 120000}); await settled();
    await page.getByText('클릭 전후 추천 API 응답을 모두 받았습니다.', {exact: true}).waitFor({timeout: 120000});
    report.checks.actual_click_comparison = true;
    report.comparison_rendered_text = await page.locator('[role="tabpanel"]:visible').innerText();
    await page.getByRole('heading', {name: '실제 클릭 전후 비교', exact: true}).scrollIntoViewIfNeeded();
    await shot('session');
    if (!report.checks.search_images || errors.length || failedRequests.length) throw new Error('browser errors or missing image rendering');
    report.status = 'PASS';
  } catch (error) {
    report.status = 'FAIL'; report.error = String(error); await shot('failure'); process.exitCode = 1;
  } finally {
    report.completed_at = new Date().toISOString();
    fs.writeFileSync(path.join(out, 'browser.json'), JSON.stringify(report, null, 2)+'\n');
    console.log(JSON.stringify({status: report.status, checks: report.checks, errors, failedRequests}));
    await browser.close();
  }
})();
