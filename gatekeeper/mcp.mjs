// MCP（Model Context Protocol）の窓口。
// 仕様: https://modelcontextprotocol.io/specification/2025-06-18
//
// NLWeb は「各インスタンスがMCPサーバーにもなる」規格で、
// 公開するツール名は仕様の Appendix A のとおり **ask**、
// 引数は query / context / prefer / meta の4つ。
// 返す中身は HTTP の /ask と同じ NLWeb のレスポンスをそのまま入れる（Appendix C.1）。
//
// 扱うのは JSON-RPC 2.0 の initialize / tools/list / tools/call / ping と
// notifications/*（通知は本文を返さない）。
//
// ツールは2本。ask（NLWeb 仕様のまま。ここに独自の変更を入れない）と、
// report_correction（受付＝AIに提供する「操作」。2026-09-09 の本人決定で追加。
// 定義は reception.mjs に1か所で持つ）。
import { parseAsk, NLWEB_VERSION } from './nlweb.mjs';
import { REPORT_TOOL } from './reception.mjs';

export const MCP_PATH = '/mcp';
export const PROTOCOL_VERSION = '2025-06-18';

export const ASK_TOOL = {
  name: 'ask',
  title: 'AI読の門番に、この自治体ページのことを聞く',
  description:
    '自治体の手続きページについて自然文で質問すると、AI読が実測した値を返します。' +
    'そのページに書かれていない項目を聞かれた場合は、書かれていないことを隠さず failure として返します。' +
    '行政機関の公式発表ではなく、第三者調査（AI読）による実測値です。',
  inputSchema: {
    type: 'object',
    properties: {
      // NLWeb 仕様 Appendix A の4引数。query だけが必須。
      query: {
        type: 'object',
        description: 'The query object containing text and filters',
        properties: {
          text: { type: 'string', description: '知りたいことを自然文で（例: 転入届の手数料はいくらですか）' },
          site: { type: 'string', description: '対象ページのパスかURL（省略時はこの門番の既定ページ）' },
        },
        required: ['text'],
      },
      context: { type: 'object', description: 'Semantic context including conversation history' },
      prefer: { type: 'object', description: 'Response preferences (streaming, formatting, mode)' },
      meta: { type: 'object', description: 'Protocol metadata, version, and session context' },
    },
    required: ['query'],
  },
};

export function rpcResult(id, result) {
  return { jsonrpc: '2.0', id, result };
}

export function rpcError(id, code, message, data) {
  return { jsonrpc: '2.0', id, error: data === undefined ? { code, message } : { code, message, data } };
}

// message: JSON-RPC のリクエスト1件
// handlers: { ask, report }（関数を1つ渡した場合は ask として扱う＝従来互換）
//   ask(parsed)  -> NLWeb のレスポンス本体
//   report(args) -> reception.mjs の executeReport の戻り（accepted / stopped_at）
// 戻り値が null のときは「通知なので本文を返さない」の意味
export async function handleRpc(message, handlers) {
  const { ask, report } = typeof handlers === 'function' ? { ask: handlers } : (handlers ?? {});
  if (!message || typeof message !== 'object' || Array.isArray(message)) {
    return rpcError(null, -32600, 'Invalid Request');
  }
  const { id, method, params } = message;
  const isNotification = id === undefined || id === null;

  // 通知（initialized など）は受け取るだけ。返事をしない。
  if (isNotification) return null;

  switch (method) {
    case 'initialize': {
      // 相手が同じ版を出してきたらその版で、違えばこちらが対応している版を返す（仕様どおり）
      const asked = params?.protocolVersion;
      return rpcResult(id, {
        protocolVersion: asked === PROTOCOL_VERSION ? asked : PROTOCOL_VERSION,
        capabilities: { tools: { listChanged: false } },
        serverInfo: { name: 'aidoku-gatekeeper', title: 'AI読 門番', version: NLWEB_VERSION },
        instructions:
          'ask ツールで、この自治体ページについて自然文で質問できます。' +
          '返る値はAI読による実測値で、行政機関の公式発表ではありません。' +
          'report_correction ツールで、実測値の誤りや元ページの更新を指摘できます' +
          '（署名検証済みのエージェントのみ。受け付けると GitHub Issue の番号が返ります）。',
      });
    }

    case 'ping':
      return rpcResult(id, {});

    case 'tools/list':
      return rpcResult(id, { tools: [ASK_TOOL, REPORT_TOOL] });

    case 'tools/call': {
      if (params?.name === REPORT_TOOL.name && report) {
        const body = await report(params?.arguments ?? {});
        return rpcResult(id, {
          content: [{ type: 'text', text: JSON.stringify(body) }],
          structuredContent: body,
          // 受付が成立しなかったら「実行できなかった」なので isError: true。
          // stopped_at（signature / validation / not-configured / github-*）が理由。
          isError: !body?.accepted,
        });
      }
      if (params?.name !== 'ask') {
        return rpcError(id, -32602, `Unknown tool: ${params?.name}`);
      }
      const parsed = parseAsk(params?.arguments);
      if (parsed.error) return rpcError(id, -32602, parsed.error);

      const body = await ask(parsed);
      // 仕様: 構造化して返す場合も、後方互換のため text にも同じJSONを入れる
      return rpcResult(id, {
        content: [{ type: 'text', text: JSON.stringify(body) }],
        structuredContent: body,
        // isError は「ツールが実行できなかった」ときのための印。
        // 「そのページには書かれていなかった(NO_RESULTS)」は正しい答えなので false のまま。
        isError: body?.error?.code === 'INVALID_QUERY',
      });
    }

    default:
      return rpcError(id, -32601, `Method not found: ${method}`);
  }
}
