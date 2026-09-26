// Dependency-free checks of the design preview, not browser or API integration proof.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const elements = new Map();
function element(selector) {
  if (!elements.has(selector)) elements.set(selector, {
    innerHTML: '', textContent: '', value: '', handlers: {},
    addEventListener(name, fn) { this.handlers[name] = fn; },
    showModal() { this.open = true; },
  });
  return elements.get(selector);
}
const context = vm.createContext({ document: { querySelector: element } });
const source = fs.readFileSync(path.join(__dirname, 'preview.js'), 'utf8');
vm.runInContext(source, context);
const run = code => vm.runInContext(code, context);
const html = () => element('#app').innerHTML;
const click = action => element('#app').handlers.click({target:{closest:()=>({dataset:{action}})}});
assert.match(html(), /登录工作空间/);
assert.doesNotMatch(source, /\b(fetch|XMLHttpRequest|localStorage|sessionStorage)\b/);
run("page='dashboard';render()");
assert.match(html(), /当前处理分布/);
assert.match(html(), /上传合成合同/);
run("openTask('A')");
assert.match(html(), /历史已确认结果/);
assert.doesNotMatch(html(), /<textarea|class="paper"/);
run("role='admin';page='dashboard';render()");
assert.doesNotMatch(html(), /上传合成合同|当前正式等级/);
run("openTask('C')");
assert.doesNotMatch(html(), /附件获取记录|<textarea|class="paper"/);
run("openTask('D')");
assert.match(html(), /不支持管理员直接重试/);
run("scene='normal';render()");
assert.match(html(), /按原版本重试/);
run("role='legal';task=tasks[0];page='workbench';scene='normal';render()");
assert.match(html(), /DEMO-PAY-01/);
assert.match(html(), /class="anchor selected"/);
run("scene='unlocatable';render()");
assert.match(html(), /无法精准定位/);
assert.doesNotMatch(html(), /class="anchor/);
run("scene='no-risk';render()");
assert.match(html(), /未发现已启用规则风险/);
assert.doesNotMatch(html(), /class="anchor/);
run("scene='normal';dirty=true;render()");
click('confirm');
assert.match(element('#notice').textContent, /请先保存/);
assert.equal(run('confirmed'), false);
run("savedOpinion='<img src=x onerror=alert(1)>';render()");
assert.doesNotMatch(html(), /<img src=x/);
assert.match(html(), /&lt;img/);
run("scene='conflict';render()");
click('save');
assert.equal(run('dirty'), true);
assert.match(element('#notice').textContent, /输入已保留/);
run("dirty=false;confirmed=true;page='reports';scene='normal';render()");
assert.match(html(), /软件采购合同 A · 文档 V2/);
click('report-preview');
assert.match(element('#dialog-title').textContent, /文档 V2/);
assert.match(element('#dialog-content').innerHTML, /软件采购合同 A/);
click('writeback');
assert.match(element('#dialog-title').textContent, /文档 V2/);
run('writeback=true;render()');
assert.match(html(), /文档 V2 · 审查 V1 · 本地模拟评论/);
click('pdf-retry');
assert.equal(run('pdfReady'), true);
run("role='business';pdfReady=false;render()");
assert.doesNotMatch(html(), /data-action="pdf-retry"|data-action="writeback"/);
run("page='dashboard';scene='empty';render()");
assert.match(html(), /还没有合同任务/);
run("scene='loading';render()");
assert.match(html(), /aria-busy="true"/);
run('reset()');
assert.match(html(), /登录工作空间/);
console.log('PASS: preview navigation, role views, recovery, risk anchors, edit guards, escaping, report states, empty/loading; no API calls.');
