#!/usr/bin/env node
/**
 * 简化版运行脚本 - 自动确认
 */

const { spawn } = require('child_process');
const { stdin, stdout, stderr } = process;

console.log('运行 Node.js 实盘交易示例...\n');

const child = spawn('node', ['real_trading_example_node.js'], {
  stdio: ['pipe', 'inherit', 'inherit']
});

// 自动输入 YES
setTimeout(() => {
  child.stdin.write('YES\n');
  child.stdin.end();
}, 500);

child.on('exit', (code) => {
  console.log(`\n进程退出，代码: ${code}`);
});
