// AIエージェント向けの窓口が、JSを実行しなくても data.html から見つかることを守る。
// 実装側のパスを正として、公開案内とのずれも止める。
import { readFileSync } from 'node:fs';
import { ASK_PATH } from '../gatekeeper/nlweb.mjs';
import { MCP_PATH } from '../gatekeeper/mcp.mjs';

const html = readFileSync(new URL('./reference/data.html', import.meta.url), 'utf8');
const origin = 'https://aidoku-gatekeeper.shoujiki-panman.workers.dev';
const askUrl = `${origin}${ASK_PATH}`;
const mcpUrl = `${origin}${MCP_PATH}`;
const section = html.match(
  /<h3[^>]+id="agent-endpoint-heading"[^>]*>[\s\S]*?(?=<h3|<\/section>)/,
)?.[0] ?? '';

let pass = 0;
let fail = 0;
function check(name, condition, detail = '') {
  if (condition) {
    pass++;
    return;
  }
  fail++;
  console.log(`FAIL ${name}${detail ? ` — ${detail}` : ''}`);
}

check('AI向け窓口の節が静的HTMLにある', section.length > 0);
check('/ask の完全URLがある', section.includes(askUrl), askUrl);
check('/mcp の完全URLがある', section.includes(mcpUrl), mcpUrl);
check('両方とも POST と案内している', (section.match(/POST https:\/\//g) ?? []).length >= 2);
check('NLWebの引数 query.text を案内している', section.includes('query.text'));
check('NLWebの引数 query.site を案内している', section.includes('query.site'));
check('対象ページに完全URLを使うと案内している', section.includes('対象ページの完全URL'));
check('MCPの tools/call を案内している', section.includes('tools/call'));
check('MCPの ask ツールを案内している', /<code>ask<\/code>\s*ツール/.test(section));
check('curlの呼び出し例がある', (section.match(/curl -X POST/g) ?? []).length >= 2);
check('Web Bot Authの署名検証を案内している', /Web Bot Auth[\s\S]*署名を検証/.test(section));
check('利用者個人を記録しないと明記している', /利用者個人[\s\S]*記録しません/.test(section));
check('書かれていない項目を推測しない', /書かれていない項目[\s\S]*推測しません/.test(section));
check('failure / NO_RESULTS を案内している', section.includes('failure') && section.includes('NO_RESULTS'));
check('Part 3の実データ説明より後にある', html.indexOf('本物のAIエージェントの来訪') < html.indexOf('agent-endpoint-heading'));
check('データの入手より前にある', html.indexOf('agent-endpoint-heading') < html.indexOf('data-heading'));

console.log(`${pass} PASS / ${fail} FAIL`);
process.exit(fail ? 1 : 0);
