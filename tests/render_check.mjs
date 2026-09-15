// 真实浏览器渲染检查（Chromium）。检查控制台错误、页面加载、桌面/移动视口布局。
// 用法: node tests/render_check.mjs
import { chromium, devices } from 'playwright';

const BASE = process.argv[2] || 'http://127.0.0.1:5000';
const TEACHER = { username: 'admin', password: 'admin123' };
const STUDENT = { username: 'S001', password: '123456' };

const findings = [];
function rec(sev, title, detail = '') {
  findings.push({ sev, title, detail });
  console.log(`[${sev}] ${title}${detail ? ' — ' + detail : ''}`);
}

async function login(context, creds) {
  const page = await context.newPage();
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
  await page.fill('input[name=username]', creds.username);
  await page.fill('input[name=password]', creds.password);
  await Promise.all([
    page.waitForNavigation({ waitUntil: 'networkidle' }).catch(() => {}),
    page.click('button[type=submit]'),
  ]);
  return page;
}

async function auditPage(context, path, label, viewport) {
  const page = await context.newPage();
  if (viewport) await page.setViewportSize(viewport);
  const consoleErrors = [];
  const pageErrors = [];
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', e => pageErrors.push(String(e)));
  const failed = [];
  page.on('requestfailed', r => failed.push(`${r.url()} ${r.failure()?.errorText || ''}`));
  let status = 0;
  try {
    const resp = await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle', timeout: 20000 });
    status = resp ? resp.status() : 0;
  } catch (e) {
    rec('严重', `${label} 加载失败`, String(e).slice(0, 100));
    await page.close();
    return;
  }
  // 横向溢出检测
  const overflow = await page.evaluate(() => {
    const de = document.documentElement;
    return { scrollW: de.scrollWidth, clientW: de.clientWidth };
  });
  const vpName = viewport ? `${viewport.width}x${viewport.height}` : 'desktop';
  if (overflow.scrollW > overflow.clientW + 2) {
    rec('一般', `${label} [${vpName}] 出现横向溢出`, `scrollW=${overflow.scrollW} > clientW=${overflow.clientW}`);
  } else {
    rec('PASS', `${label} [${vpName}] 无横向溢出 (status ${status})`);
  }
  // 过滤掉可接受的 CDN/pyodide 相关错误分类
  const realErrors = [...consoleErrors, ...pageErrors].filter(Boolean);
  if (realErrors.length) {
    rec('一般', `${label} [${vpName}] 控制台错误 ${realErrors.length} 条`, realErrors.slice(0, 3).join(' | ').slice(0, 240));
  }
  const realFailed = failed.filter(f => !f.includes('favicon'));
  if (realFailed.length) {
    rec('优化', `${label} [${vpName}] 资源加载失败 ${realFailed.length} 条`, realFailed.slice(0, 3).join(' | ').slice(0, 240));
  }
  await page.close();
}

(async () => {
  const exe = process.env.CHROME_EXE || undefined;
  const browser = await chromium.launch(exe ? { executablePath: exe } : {});
  console.log('== 桌面视口 (Chromium 1280x800) ==');
  const desktop = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  // 登录页（匿名）
  await auditPage(desktop, '/login', '登录页');
  // 学生端
  const sctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  await login(sctx, STUDENT);
  for (const [p, l] of [['/student/home', '学生首页'], ['/student/records', '学生记录'],
    ['/student/achievements', '学生成就'], ['/student/experiment/ION', '实验工作台']]) {
    await auditPage(sctx, p, l);
  }
  // 教师端
  const tctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  await login(tctx, TEACHER);
  for (const [p, l] of [['/teacher', '教师审核台'], ['/teacher/experiments', '实验管理'],
    ['/teacher/students', '学生管理'], ['/teacher/analytics', '学情分析']]) {
    await auditPage(tctx, p, l);
  }

  console.log('\n== 移动端视口 (iPhone 12 390x844) ==');
  const mobile = await browser.newContext({ ...devices['iPhone 12'] });
  await login(mobile, STUDENT);
  for (const [p, l] of [['/student/home', '学生首页'], ['/student/experiment/ION', '实验工作台']]) {
    await auditPage(mobile, p, l, { width: 390, height: 844 });
  }
  const mobileT = await browser.newContext({ ...devices['iPhone 12'] });
  await login(mobileT, TEACHER);
  await auditPage(mobileT, '/teacher', '教师审核台', { width: 390, height: 844 });
  await auditPage(mobileT, '/teacher/experiments', '实验管理', { width: 390, height: 844 });

  await browser.close();

  const bad = findings.filter(f => f.sev !== 'PASS').length;
  console.log(`\n== 渲染检查完成：${findings.length} 项，其中 ${bad} 项需关注 ==`);
})();
