// @ts-check
const https = require('https');
const fs = require('fs');
const path = require('path');

/**
 * 下载币安 SDK 文档
 */
const docs = [
  {
    name: 'Spot API 文档',
    url: 'https://binance-docs.github.io/apidocs/spot/cn/',
    file: 'spot-api.html'
  },
  {
    name: 'Margin API 文档',
    url: 'https://binance-docs.github.io/apidocs/margin/cn/',
    file: 'margin-api.html'
  },
  {
    name: 'GitHub 仓库',
    url: 'https://github.com/binance/binance-connector-node',
    file: 'github-repo.md'
  }
];

/**
 * 下载文件
 */
async function downloadFile(url, filepath) {
  return new Promise((resolve, reject) => {
    https.get(url, (response) => {
      if (response.statusCode === 301 || response.statusCode === 302) {
        return downloadFile(response.headers.location, filepath).then(resolve).catch(reject);
      }

      const fileStream = fs.createWriteStream(filepath);
      response.pipe(fileStream);

      fileStream.on('finish', () => {
        fileStream.close();
        resolve(true);
      });
    }).on('error', (err) => {
      fs.unlink(filepath, () => {});
      reject(err);
    });
  });
}

/**
 * 创建文档说明
 */
function createReadme() {
  const readme = `# 币安 API SDK 文档

## 安装
\`\`\`bash
npm install @binance/connector
\`\`\`

## 资源链接
- 官方文档: https://binance-docs.github.io/apidocs/spot/cn/
- GitHub: https://github.com/binance/binance-connector-node
- SDK 示例: https://github.com/binance/binance-connector-node/tree/master/examples

## 市场数据接口
- /api/v3/klines - K线数据
- /api/v3/ticker/24hr - 24小时价格变动
- /api/v3/depth - 订单簿深度
- /api/v3/trades - 最近成交

## 账户接口 (需要 API Key)
- /api/v3/account - 账户信息
- /api/v3/order - 下单
- /api/v3/openOrders - 查询当前挂单
`;

  fs.writeFileSync(path.join(__dirname, 'SDK-README.md'), readme, 'utf-8');
  console.log('✓ SDK-README.md 已创建');
}

async function main() {
  console.log('开始下载币安 SDK 文档...\n');

  // 创建 docs 目录
  const docsDir = path.join(__dirname, 'docs');
  if (!fs.existsSync(docsDir)) {
    fs.mkdirSync(docsDir, { recursive: true });
  }

  createReadme();

  console.log('\n提示: 访问以下链接获取完整文档:');
  console.log('  Spot API: https://binance-docs.github.io/apidocs/spot/cn/');
  console.log('  Margin API: https://binance-docs.github.io/apidocs/margin/cn/');
  console.log('  GitHub: https://github.com/binance/binance-connector-node');
}

main().catch(console.error);
