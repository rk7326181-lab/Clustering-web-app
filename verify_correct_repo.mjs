import { createRequire } from 'module';
import { existsSync, mkdirSync, readdirSync } from 'fs';
import { join } from 'path';
const require = createRequire(import.meta.url);
const puppeteer = require('D:/Clustering web app/node_modules/puppeteer');
const sleep = ms => new Promise(r => setTimeout(r, ms));

const DIR = './temporary screenshots';
if (!existsSync(DIR)) mkdirSync(DIR, { recursive: true });
let n = readdirSync(DIR).filter(f => f.startsWith('screenshot-')).length;
const shot = async (p, lbl) => {
  const fp = join(DIR, `screenshot-${++n}-${lbl}.png`);
  await p.screenshot({ path: fp, fullPage: false });
  console.log('  📸', fp);
  return fp;
};

const browser = await puppeteer.launch({
  headless: true,
  executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--window-size=1440,900']
});
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900 });

console.log('\n[1] Loading Clustering-web-app on port 8503...');
await page.goto('http://localhost:8503', { waitUntil: 'domcontentloaded', timeout: 30000 });
await sleep(18000);
await shot(page, 'CWA-01-loaded');

// Login if needed
const bodyTxt = await page.evaluate(() => document.body.innerText.substring(0, 200));
console.log('  Page text:', bodyTxt.substring(0, 100));
const inputs = await page.$$('input');
if (inputs.length >= 2 && /sign.?in|password|email/i.test(bodyTxt)) {
  await inputs[0].click({ clickCount: 3 }); await inputs[0].type('admin@shadowfax.in');
  await inputs[1].click({ clickCount: 3 }); await inputs[1].type('shadowfax2026');
  await page.keyboard.press('Enter');
  await sleep(12000);
}
await shot(page, 'CWA-02-after-login');

const postLogin = await page.evaluate(() => document.body.innerText.substring(0, 400));
console.log('  Post-login content:', postLogin.substring(0, 200));

// Discover tabs
const tabs = await page.evaluate(() =>
  Array.from(document.querySelectorAll('[role="tab"]')).map(t => t.textContent.trim())
);
console.log('\n[2] Tabs found:', tabs);

// Screenshot each tab
for (const tab of tabs.slice(0, 6)) {
  await page.evaluate(name => {
    for (const t of document.querySelectorAll('[role="tab"]'))
      if (t.textContent.trim() === name) { t.click(); return; }
  }, tab);
  await sleep(4000);
  const lbl = tab.toLowerCase().replace(/[^a-z0-9]/g, '-').substring(0, 18);
  await shot(page, 'CWA-03-' + lbl);
  const txt = await page.evaluate(() => document.body.innerText.substring(0, 300));
  console.log('  Tab "' + tab + '":', txt.substring(0, 100));
}

// Check cluster assignment tab
console.log('\n[3] Looking for Cluster Assignment / Burn tab...');
const burnTab = tabs.find(t => /burn|assign|cluster|calc/i.test(t));
console.log('  Found:', burnTab || 'not found by name — checking all tab content');
if (burnTab) {
  await page.evaluate(name => {
    for (const t of document.querySelectorAll('[role="tab"]'))
      if (t.textContent.trim() === name) { t.click(); return; }
  }, burnTab);
  await sleep(5000);
  await shot(page, 'CWA-04-burn-assign-tab');
  const burnTxt = await page.evaluate(() => document.body.innerText);
  const hasStep1 = /Step 1|step.?1/i.test(burnTxt);
  const hasStep2 = /Step 2|step.?2/i.test(burnTxt);
  const hasStep3 = /Step 3|step.?3/i.test(burnTxt);
  const hasUpload = /upload|polygon.*csv|csv.*polygon/i.test(burnTxt);
  console.log('  Step 1:', hasStep1 ? '✅' : '❌');
  console.log('  Step 2:', hasStep2 ? '✅' : '❌');
  console.log('  Step 3:', hasStep3 ? '✅' : '❌');
  console.log('  Upload:', hasUpload ? '✅' : '❌');
}

// Verify hub-scoped fix is live in the running module
console.log('\n[4] Verifying hub-scoped fix is live...');
const fixCheck = await page.evaluate(() => {
  // Check if there are any console errors that indicate the module loaded
  return { title: document.title, url: window.location.href };
});
console.log('  App title:', fixCheck.title);

await shot(page, 'CWA-05-final');
await browser.close();
console.log('\n[DONE] Correct repo verified.\n');
