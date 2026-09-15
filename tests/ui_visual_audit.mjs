import { chromium, firefox, webkit } from 'playwright';

const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5000';
const browserName = process.env.UI_BROWSER || 'chromium';
const auditLevel = process.env.UI_LEVEL || 'full';
const browserType = { chromium, firefox, webkit }[browserName];
if (!browserType) throw new Error(`不支持的浏览器：${browserName}`);

const executablePath = browserName === 'chromium' ? process.env.CHROME_EXE : undefined;
const browser = await browserType.launch(executablePath ? { executablePath } : {});
const findings = [];
const allViewports = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'tablet-landscape', width: 1024, height: 768 },
  { name: 'tablet-portrait', width: 768, height: 1024 },
  { name: 'mobile', width: 390, height: 844 },
];
const viewports = auditLevel === 'desktop' ? allViewports.slice(0, 1) : (auditLevel === 'cross' ? allViewports.filter(item => item.name === 'desktop' || item.name === 'mobile') : allViewports);

const fixedStudentPages = [
  ['/student/home', '学生首页'],
  ['/student/records', '我的实验'],
  ['/student/achievements', '报告与荣誉'],
  ['/student/experiment/ION', '实验工作台'],
];
const fixedTeacherPages = [
  ['/teacher', '审核队列'],
  ['/teacher/analytics', '学情观测'],
  ['/teacher/experiments', '实验管理'],
  ['/teacher/students', '学生管理'],
];

function record(ok, label, detail = '') {
  findings.push({ ok, label, detail });
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${label}${detail ? ` — ${detail}` : ''}`);
}

async function login(context, username, password) {
  const page = await context.newPage();
  await page.goto(`${base}/login`, { waitUntil: 'domcontentloaded' });
  await page.fill('input[name=username]', username);
  await page.fill('input[name=password]', password);
  await Promise.all([page.waitForURL(url => !url.pathname.endsWith('/login'), { timeout: 6000 }), page.click('button[type=submit]')]);
  return page;
}

async function discoverPath(page, startPath, selector) {
  await page.goto(`${base}${startPath}`, { waitUntil: 'domcontentloaded' });
  const href = await page.locator(selector).first().getAttribute('href').catch(() => null);
  return href && href.startsWith('/') ? href : null;
}

async function auditPage(context, path, label, viewport) {
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  const response = await page.goto(`${base}${path}`, { waitUntil: 'domcontentloaded', timeout: 20000 }).catch(() => null);
  await page.waitForTimeout(60);
  if (!response || response.status() >= 400) {
    record(false, `${browserName} ${viewport.name} ${label}`, `页面状态 ${response?.status() ?? '加载失败'}`);
    await page.close();
    return null;
  }
  const metrics = await page.evaluate(() => {
    const root = document.documentElement;
    const title = document.querySelector('.teacher-v4-heading h1, .page-hero h1, .intro-panel h1, .experiment-banner h1, .report-toolbar h1');
    const workbench = document.querySelector('.teacher-v4-page');
    const subnav = document.querySelector('.teacher-subnav');
    const expected = innerWidth <= 680 ? { H1: 32, H2: 22, H3: 17 } : { H1: 40, H2: 24, H3: 18 };
    const headingErrors = [...document.querySelectorAll('main h1, main h2, main h3')].filter(element => !element.closest('.academic-report-paper, .final-academic-report, .report-page, .sakura-certificate')).filter(element => Math.abs(parseFloat(getComputedStyle(element).fontSize) - expected[element.tagName]) > 0.5).length;
    const malformedIcons = [...document.querySelectorAll('svg.lucide')].filter(icon => {
      const rect = icon.getBoundingClientRect();
      return rect.width && rect.height && Math.abs(rect.width - rect.height) > 1;
    }).length;
    return {
      overflow: root.scrollWidth - root.clientWidth,
      titleSize: title ? parseFloat(getComputedStyle(title).fontSize) : null,
      pageWidth: workbench ? Math.round(workbench.getBoundingClientRect().width) : null,
      pageLeft: workbench ? Math.round(workbench.getBoundingClientRect().left) : null,
      subnavWidth: subnav ? Math.round(subnav.getBoundingClientRect().width) : null,
      subnavHeight: subnav ? Math.round(subnav.getBoundingClientRect().height) : null,
      malformedIcons,
      headingErrors,
    };
  });
  const expectedTitle = viewport.width <= 680 ? 32 : 40;
  const titleOk = metrics.titleSize === null || Math.abs(metrics.titleSize - expectedTitle) < 0.5;
  const benignErrors = errors.filter(error => !/favicon|pyodide|cdn\.jsdelivr/i.test(error));
  const ok = metrics.overflow <= 2 && metrics.malformedIcons === 0 && metrics.headingErrors === 0 && titleOk && benignErrors.length === 0;
  record(ok, `${browserName} ${viewport.name} ${label}`, `overflow=${metrics.overflow}, title=${metrics.titleSize ?? 'n/a'}, heading-errors=${metrics.headingErrors}, icon-ratio-errors=${metrics.malformedIcons}${benignErrors.length ? `, console=${benignErrors.length}` : ''}`);
  await page.close();
  return metrics;
}

for (const viewport of viewports) {
  const student = await browser.newContext({ viewport });
  const studentPage = await login(student, 'S001', '123456');
  const reportPath = await discoverPath(studentPage, '/student/records', 'a[href*="/report/"]');
  for (const [path, label] of fixedStudentPages) await auditPage(student, path, label, viewport);
  if (reportPath) await auditPage(student, reportPath, '学生报告', viewport);
  await student.close();

  const teacher = await browser.newContext({ viewport });
  const teacherPage = await login(teacher, 'admin', 'admin123');
  const reviewPath = await discoverPath(teacherPage, '/teacher', 'a.review-action');
  const editorPath = await discoverPath(teacherPage, '/teacher/experiments', 'a[href$="/draft"]');
  const geometry = {};
  for (const [path, label] of fixedTeacherPages) geometry[label] = await auditPage(teacher, path, label, viewport);
  if (reviewPath) await auditPage(teacher, reviewPath, '教师报告审核', viewport);
  if (editorPath) await auditPage(teacher, editorPath, '实验编辑器', viewport);
  const review = geometry['审核队列'], analytics = geometry['学情观测'];
  if (review && analytics) {
    const same = review.pageWidth === analytics.pageWidth && review.pageLeft === analytics.pageLeft && review.subnavWidth === analytics.subnavWidth && review.subnavHeight === analytics.subnavHeight;
    record(same, `${browserName} ${viewport.name} 审核双页面尺度一致`, `page=${review.pageWidth}/${analytics.pageWidth}, left=${review.pageLeft}/${analytics.pageLeft}, subnav=${review.subnavWidth}x${review.subnavHeight}/${analytics.subnavWidth}x${analytics.subnavHeight}`);
  }
  await teacher.close();
}

await browser.close();
const failed = findings.filter(item => !item.ok);
console.log(`\n${browserName} UI 验收：${findings.length - failed.length}/${findings.length} 通过`);
if (failed.length) process.exitCode = 1;
