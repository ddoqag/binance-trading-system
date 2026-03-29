// @ts-check
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

/**
 * 爬取币安 API 文档
 */
async function scrapeBinanceAPI() {
  // 启动浏览器（使用系统 Chrome）
  const browser = await chromium.launch({
    channel: 'chrome',
    headless: false, // 有头模式，方便观察
  });

  const page = await browser.newPage();
  const apiData = [];

  try {
    // 导航到目标页面
    console.log('正在打开页面...');
    await page.goto('https://developers.binance.com/docs/zh-CN/margin_trading/common-definition', {
      waitUntil: 'domcontentloaded',
      timeout: 30000
    });

    // 等待页面加载
    await page.waitForTimeout(3000);

    console.log('页面已加载，开始提取侧边栏链接...');

    // 提取侧边栏所有 API 链接
    const sidebarLinks = await page.evaluate(() => {
      const links = [];
      // 查找侧边栏导航链接
      const navElements = document.querySelectorAll('a[href*="/docs/zh-CN/margin_trading/"]');
      navElements.forEach(el => {
        const href = el.getAttribute('href');
        const text = el.textContent?.trim() || '';
        if (href && text) {
          links.push({
            url: href.startsWith('http') ? href : `https://developers.binance.com${href}`,
            name: text
          });
        }
      });
      return links;
    });

    console.log(`找到 ${sidebarLinks.length} 个链接`);
    console.log('链接列表:', sidebarLinks);

    // TODO: 这里需要你决定爬取策略
    // 这是一个关键的决策点：
    // 1. 你是想爬取所有链接，还是只爬取特定分类的链接？
    // 2. 每个页面的 API 文档结构可能不同，你想如何提取信息？
    // 3. 对于参数说明，你想提取哪些字段（名称、类型、是否必填、描述等）？

    // 先尝试访问第一个 API 页面来分析结构
    if (sidebarLinks.length > 0) {
      const firstApiLink = sidebarLinks.find(link =>
        !link.name.includes('通用') && !link.name.includes('定义') && !link.name.includes('错误')
      ) || sidebarLinks[0];

      console.log(`正在分析页面结构: ${firstApiLink.name}`);
      await page.goto(firstApiLink.url, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(3000);

      // 获取页面内容用于分析
      const pageContent = await page.content();
      console.log('页面已加载，请在浏览器中查看结构，然后告诉我如何提取信息...');

      // 保存页面内容供分析
      fs.writeFileSync(path.join(__dirname, 'page-sample.html'), pageContent, 'utf-8');
      console.log('页面样本已保存到 page-sample.html');
    }

    // 保存初步数据
    const result = {
      timestamp: new Date().toISOString(),
      sidebarLinks,
      apiData
    };

    fs.writeFileSync(
      path.join(__dirname, 'binance-api-links.json'),
      JSON.stringify(result, null, 2),
      'utf-8'
    );

    console.log('链接列表已保存到 binance-api-links.json');
    console.log('请查看浏览器中的页面结构，然后告诉我如何提取 API 详情和参数！');

  } catch (error) {
    console.error('爬取出错:', error);
  } finally {
    // 保持浏览器打开，方便查看页面结构
    console.log('浏览器保持打开状态，请分析页面结构后告诉我下一步...');
    // 如需自动关闭，取消下面这行的注释：
    // await browser.close();
  }
}

// 运行爬取
scrapeBinanceAPI();
