import { chromium, devices } from 'playwright';
const BASE = 'http://127.0.0.1:5000';
const OUT = 'runtime/e2e-shots';
import { mkdirSync } from 'fs';
mkdirSync(OUT, { recursive: true });
const exe = process.env.CHROME_EXE;

async function login(ctx, u, p) {
  const page = await ctx.newPage();
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
  await page.fill('input[name=username]', u);
  await page.fill('input[name=password]', p);
  await Promise.all([page.waitForNavigation({ waitUntil: 'networkidle' }).catch(()=>{}), page.click('button[type=submit]')]);
  return page;
}
async function shot(ctx, path, name) {
  const page = await ctx.newPage();
  await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle', timeout: 20000 }).catch(()=>{});
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
  console.log(`saved ${name}.png`);
  await page.close();
}
(async () => {
  const b = await chromium.launch(exe ? { executablePath: exe } : {});
  const anon = await b.newContext({ viewport: { width: 1280, height: 800 } });
  await shot(anon, '/login', '01-login');
  const s = await b.newContext({ viewport: { width: 1280, height: 800 } });
  await login(s, 'S001', '123456');
  await shot(s, '/student/home', '02-student-home');
  await shot(s, '/student/experiment/ION', '03-experiment-workbench');
  await shot(s, '/student/records', '04-student-records');
  const t = await b.newContext({ viewport: { width: 1280, height: 800 } });
  await login(t, 'admin', 'admin123');
  await shot(t, '/teacher', '05-teacher-dashboard');
  await shot(t, '/teacher/experiments', '06-teacher-experiments');
  await shot(t, '/teacher/students', '07-teacher-students');
  await shot(t, '/teacher/analytics', '08-teacher-analytics');
  const m = await b.newContext({ ...devices['iPhone 12'] });
  await login(m, 'S001', '123456');
  await shot(m, '/student/home', '09-mobile-student-home');
  await b.close();
})();
