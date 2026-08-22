/*!
 * ask-ai-button — このページを「いつも使っているAI」で開くボタン
 * 依存ゼロ / Shadow DOM / 1ファイル。MIT.
 */
(function () {
  "use strict";
  if (window.__askAiButtonLoaded) return;
  window.__askAiButtonLoaded = true;

  var script = document.currentScript;
  var ds = (script && script.dataset) || {};

  var DEFAULTS = {
    position: "bottom-right",
    providers: "chatgpt,claude,gemini,grok,perplexity",
    actions: "summary,explain,ask,translate",
    selector: "",
    label: "AIで開く",
    maxUrlChars: "8000",
    theme: "auto",
  };
  var cfg = {};
  for (var k in DEFAULTS) cfg[k] = ds[k] != null ? ds[k] : DEFAULTS[k];
  var MAX_URL = parseInt(cfg.maxUrlChars, 10) || 1800;

  var PROVIDERS = {
    chatgpt: {
      name: "ChatGPT",
      color: "#0f9d76",
      url: function (q) { return "https://chatgpt.com/?q=" + q; },
      supportsQuery: true,
      icon: '<path d="M12 2 3 7v10l9 5 9-5V7l-9-5Zm0 2.3 6.8 3.8v7.8L12 19.7 5.2 15.9V8.1L12 4.3Z"/><circle cx="12" cy="12" r="3"/>',
    },
    claude: {
      name: "Claude",
      color: "#d97757",
      url: function (q) { return "https://claude.ai/new?q=" + q; },
      supportsQuery: true,
      icon: '<path d="M5 19 10.2 5h3.6L19 19h-3l-1-3H9l-1 3H5Zm4.7-5.4h4.6L12 7.6l-2.3 6Z"/>',
    },
    gemini: {
      name: "Gemini",
      color: "#4285f4",
      url: function () { return "https://gemini.google.com/app"; },
      supportsQuery: false,
      icon: '<path d="M12 2c.5 4.7 3.3 7.5 8 8-4.7.5-7.5 3.3-8 8-.5-4.7-3.3-7.5-8-8 4.7-.5 7.5-3.3 8-8Z"/>',
    },
    grok: {
      name: "Grok",
      color: "#111111",
      url: function (q) { return "https://grok.com/?q=" + q; },
      supportsQuery: true,
      icon: '<path d="M4 20 20 4M9 4h11v11"/>',
    },
    perplexity: {
      name: "Perplexity",
      color: "#20b8cd",
      url: function (q) { return "https://www.perplexity.ai/search?q=" + q; },
      supportsQuery: true,
      icon: '<path d="M12 3v18M4 7.5 12 12l8-4.5M4 16.5 12 12l8 4.5"/>',
    },
  };

  var ACTIONS = {
    summary: {
      label: "要約してもらう",
      hint: "要点を箇条書きで",
      prompt: "次のWebページの内容を日本語で要約してください。重要な主張を箇条書きで5つ以内にまとめ、最後に一言でまとめてください。",
    },
    explain: {
      label: "やさしく解説してもらう",
      hint: "前提知識ゼロ向け",
      prompt: "次のWebページの内容を、前提知識のない人にもわかるように日本語で解説してください。専門用語が出てきたら、その都度かみ砕いて説明してください。",
    },
    ask: {
      label: "このページについて質問する",
      hint: "内容を読ませてから会話",
      prompt: "次のWebページの内容を読んで把握してください。読み終えたら「準備できました」とだけ答えて、私からの質問を待ってください。ページに書かれていないことは推測せず、書かれていないと答えてください。",
    },
    translate: {
      label: "英訳してもらう",
      hint: "自然な英語に",
      prompt: "Translate the following web page into natural English. Keep the heading structure and lists as they are.",
    },

    // ▼▼▼ ここから AI読 の追加。上流の ask-ai-button.js には無い ▼▼▼
    // 上流の4つは読み物向けで、AI読の目的（自治体の手続きを実際に済ませる手伝い）と
    // 合わない。差し替えではなく追加なので、上流を更新するときはこのブロックだけ
    // 移せばよい。data-actions="procedure" で、これだけを出している。
    procedure: {
      label: "この手続きを手伝ってもらう",
      hint: "区のページを調べて、持ち物リストまで",
      prompt: [
        "あなたはこれから、私が自治体の手続きを実際に済ませるのを手伝います。",
        "下に貼るのは「AI読（アイドク）」という第三者調査の実測結果です。",
        "行政機関の公式発表ではありません。",
        "",
        "1. まず、私がどの自治体のどの手続きをしようとしているかを確認してください。",
        "2. 実測で「読めた」となっている項目は、区の公式ページ（下に出ているURL）を開いて、",
        "   そこに書かれている内容を答えてください。あなたの記憶で答えないでください。",
        "3. 実測で「このページからは分かりません」となっている項目は、",
        "   一般論や他の自治体の値で埋めないでください。",
        "   「区のページには書かれていない」と伝えたうえで、",
        "   区役所の担当窓口に電話で確認するよう案内してください。",
        "   金額・期限・持ち物は、間違えると窓口で差し戻される項目です。",
        "   確認を促すのはサボりではなく、ここでは正解です。",
        "4. 最後に、当日持っていくものと、行く前に確認することを箇条書きにしてください。",
        "",
        "答えの末尾には、参照した区の公式ページのURLと、",
        "実測がいつのものかを必ず書いてください。",
      ].join("\n"),
    },
    // ▲▲▲ ここまで AI読 の追加 ▲▲▲
  };

  function pickRoot() {
    if (cfg.selector) {
      var picked = document.querySelector(cfg.selector);
      if (picked) return picked;
    }
    var candidates = ["article", "main", '[role="main"]', "#content", ".content", ".post", ".entry-content"];
    for (var i = 0; i < candidates.length; i++) {
      var el = document.querySelector(candidates[i]);
      if (el && el.innerText && el.innerText.trim().length > 200) return el;
    }
    var best = document.body, bestLen = 0;
    var blocks = document.body.querySelectorAll("div,section");
    for (var j = 0; j < blocks.length; j++) {
      var b = blocks[j];
      if (b.querySelectorAll("div,section").length > 6) continue;
      var len = (b.innerText || "").trim().length;
      if (len > bestLen) { bestLen = len; best = b; }
    }
    return best;
  }

  var SKIP = /^(SCRIPT|STYLE|NOSCRIPT|NAV|HEADER|FOOTER|ASIDE|FORM|IFRAME|SVG|BUTTON|TEMPLATE)$/;

  function toMarkdown(root) {
    var out = [];
    walk(root, out, 0);
    return out.join("\n").replace(/\n{3,}/g, "\n\n").trim();
  }

  function inline(el) {
    var txt = "";
    el.childNodes.forEach(function (n) {
      if (n.nodeType === 3) { txt += n.nodeValue; return; }
      if (n.nodeType !== 1) return;
      var tag = n.tagName;
      if (SKIP.test(tag) || n.hasAttribute("data-ai-ignore")) return;
      var inner = inline(n);
      if (tag === "A" && n.getAttribute("href")) {
        var href = n.href || n.getAttribute("href");
        txt += inner.trim() ? "[" + inner.trim() + "](" + href + ")" : "";
      } else if (tag === "STRONG" || tag === "B") txt += "**" + inner + "**";
      else if (tag === "EM" || tag === "I") txt += "*" + inner + "*";
      else if (tag === "CODE") txt += "`" + inner + "`";
      else if (tag === "BR") txt += "\n";
      else txt += inner;
    });
    return txt.replace(/[ \t]+/g, " ");
  }

  function walk(el, out, depth) {
    el.childNodes.forEach(function (n) {
      if (n.nodeType === 3) {
        var t = n.nodeValue.trim();
        if (t && depth === 0) out.push(t);
        return;
      }
      if (n.nodeType !== 1) return;
      var tag = n.tagName;
      if (SKIP.test(tag) || n.hasAttribute("data-ai-ignore")) return;

      if (/^H[1-6]$/.test(tag)) {
        out.push("\n" + "#".repeat(+tag[1]) + " " + inline(n).trim() + "\n");
      } else if (tag === "P") {
        var p = inline(n).trim();
        if (p) out.push(p + "\n");
      } else if (tag === "UL" || tag === "OL") {
        var i = 1;
        n.querySelectorAll(":scope > li").forEach(function (li) {
          var mark = tag === "OL" ? i++ + ". " : "- ";
          out.push(mark + inline(li).trim());
        });
        out.push("");
      } else if (tag === "PRE") {
        out.push("```\n" + (n.innerText || "").replace(/\n+$/, "") + "\n```\n");
      } else if (tag === "BLOCKQUOTE") {
        out.push("> " + inline(n).trim().replace(/\n/g, "\n> ") + "\n");
      } else if (tag === "TABLE") {
        var rows = [];
        n.querySelectorAll("tr").forEach(function (tr) {
          var cells = [];
          tr.querySelectorAll("th,td").forEach(function (td) { cells.push(inline(td).trim()); });
          rows.push("| " + cells.join(" | ") + " |");
        });
        if (rows.length) {
          var cols = (rows[0].match(/\|/g) || []).length - 1;
          rows.splice(1, 0, "|" + " --- |".repeat(cols));
          out.push(rows.join("\n") + "\n");
        }
      } else if (tag === "IMG") {
        var alt = n.getAttribute("alt");
        if (alt) out.push("![" + alt + "](" + n.src + ")");
      } else {
        walk(n, out, depth + 1);
      }
    });
  }

  function pageContext() {
    var title = (document.querySelector("h1") && document.querySelector("h1").innerText.trim()) || document.title;
    return { title: title, url: location.href, body: toMarkdown(pickRoot()) };
  }

  function buildPrompt(actionKey) {
    var ctx = pageContext();
    var head = ACTIONS[actionKey].prompt;
    return {
      full: head + "\n\n---\n# " + ctx.title + "\n出典: " + ctx.url + "\n\n" + ctx.body + "\n---",
      short: head + "\n\n対象のページ: " + ctx.title + "\n" + ctx.url + "\n（このURLを開いて本文を読んでから答えてください。開けない場合はその旨を伝えてください。）",
      ctx: ctx,
    };
  }

  function copy(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    return new Promise(function (res) {
      var ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); } catch (e) {}
      document.body.removeChild(ta); res();
    });
  }

  function send(providerKey, actionKey) {
    var p = PROVIDERS[providerKey];
    var built = buildPrompt(actionKey);
    localStorage.setItem("askai:provider", providerKey);

    if (!p.supportsQuery) {
      copy(built.full).then(function () {
        toast(p.name + " はURLでプロンプトを受け取れないので、全文をコピーしました。開いた画面に貼り付けてください。");
        window.open(p.url(""), "_blank", "noopener");
      });
      return;
    }
    var enc = encodeURIComponent(built.full);
    if (enc.length <= MAX_URL) {
      window.open(p.url(enc), "_blank", "noopener");
      toast(p.name + " を開きました。");
    } else {
      copy(built.full).then(function () {
        window.open(p.url(encodeURIComponent(built.short)), "_blank", "noopener");
        toast("本文が長いのでURLではなくクリップボードに全文を入れました。必要なら貼り付けてください。");
      });
    }
  }

  var host = document.createElement("div");
  host.setAttribute("data-ai-ignore", "");
  var root = host.attachShadow({ mode: "open" });
  var providerKeys = cfg.providers.split(",").map(function (s) { return s.trim(); }).filter(function (s) { return PROVIDERS[s]; });
  var actionKeys = cfg.actions.split(",").map(function (s) { return s.trim(); }).filter(function (s) { return ACTIONS[s]; });
  var current = localStorage.getItem("askai:provider");
  if (providerKeys.indexOf(current) < 0) current = providerKeys[0];

  var pos = cfg.position;
  var vertical = pos.indexOf("top") === 0 ? "top:20px;" : "bottom:20px;";
  var horizontal = pos.indexOf("left") > -1 ? "left:20px;" : "right:20px;";
  var fixed = pos === "inline" ? "position:relative;" : "position:fixed;" + vertical + horizontal;
  var openUp = pos.indexOf("bottom") === 0;

  root.innerHTML =
    "<style>" +
    ":host{all:initial}" +
    "*{box-sizing:border-box;font-family:system-ui,-apple-system,'Hiragino Kaku Gothic ProN','Noto Sans JP',sans-serif}" +
    ".wrap{" + fixed + "z-index:2147483000;display:flex;flex-direction:column;align-items:" + (pos.indexOf("left") > -1 ? "flex-start" : "flex-end") + ";gap:8px}" +
    ".btn{display:inline-flex;align-items:center;gap:8px;padding:10px 16px;border-radius:999px;border:1px solid var(--bd);background:var(--bg);color:var(--fg);font-size:14px;font-weight:600;cursor:pointer;box-shadow:0 4px 16px rgba(0,0,0,.14);transition:transform .12s ease}" +
    ".btn:hover{transform:translateY(-1px)}" +
    ".dot{width:8px;height:8px;border-radius:50%;background:currentColor}" +
    ".panel{width:290px;padding:8px;border-radius:14px;border:1px solid var(--bd);background:var(--bg);color:var(--fg);box-shadow:0 12px 40px rgba(0,0,0,.18);display:none;order:" + (openUp ? "-1" : "1") + "}" +
    ".panel.open{display:block}" +
    ".sec{font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:var(--mut);padding:8px 10px 4px}" +
    ".item{display:flex;flex-direction:column;gap:2px;width:100%;text-align:left;padding:9px 10px;border:0;border-radius:9px;background:transparent;color:var(--fg);font-size:14px;cursor:pointer}" +
    ".item:hover{background:var(--hov)}" +
    ".item small{color:var(--mut);font-size:11.5px}" +
    ".provs{display:flex;flex-wrap:wrap;gap:6px;padding:4px 10px 8px}" +
    ".prov{display:inline-flex;align-items:center;gap:5px;padding:6px 10px;border-radius:999px;border:1px solid var(--bd);background:transparent;color:var(--fg);font-size:12.5px;cursor:pointer}" +
    ".prov[aria-pressed='true']{border-color:currentColor;background:var(--hov);font-weight:700}" +
    ".prov svg{width:13px;height:13px;fill:none;stroke:currentColor;stroke-width:1.8}" +
    ".toast{max-width:290px;padding:9px 13px;border-radius:10px;background:#111;color:#fff;font-size:12.5px;line-height:1.5;opacity:0;transition:opacity .2s;pointer-events:none}" +
    ".toast.show{opacity:.95}" +
    ".wrap{--bg:#fff;--fg:#16181d;--mut:#6b7280;--bd:#e3e5ea;--hov:#f3f4f6}" +
    (cfg.theme !== "light" ? "@media(prefers-color-scheme:dark){.wrap{--bg:#1b1d22;--fg:#f1f2f4;--mut:#9aa1ac;--bd:#33363d;--hov:#2a2d34}.toast{background:#f1f2f4;color:#16181d}}" : "") +
    (cfg.theme === "dark" ? ".wrap{--bg:#1b1d22;--fg:#f1f2f4;--mut:#9aa1ac;--bd:#33363d;--hov:#2a2d34}" : "") +
    "</style>" +
    '<div class="wrap">' +
    '<div class="toast" part="toast"></div>' +
    '<button class="btn" type="button" aria-haspopup="true" aria-expanded="false">' +
    '<span class="dot"></span><span class="lbl"></span><span aria-hidden="true">▾</span></button>' +
    '<div class="panel" role="menu">' +
    '<div class="sec">やってもらうこと</div><div class="acts"></div>' +
    '<div class="sec">使うAI</div><div class="provs"></div>' +
    "</div></div>";

  var btn = root.querySelector(".btn");
  var lbl = root.querySelector(".lbl");
  var panel = root.querySelector(".panel");
  var acts = root.querySelector(".acts");
  var provs = root.querySelector(".provs");
  var toastEl = root.querySelector(".toast");
  var toastTimer;

  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove("show"); }, 4000);
  }

  function paintLabel() {
    lbl.textContent = cfg.label + "（" + PROVIDERS[current].name + "）";
    btn.style.color = PROVIDERS[current].color;
  }

  actionKeys.forEach(function (key) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "item";
    b.setAttribute("role", "menuitem");
    b.innerHTML = "<span>" + ACTIONS[key].label + "</span><small>" + ACTIONS[key].hint + "</small>";
    b.addEventListener("click", function () { close(); send(current, key); });
    acts.appendChild(b);
  });

  var copyBtn = document.createElement("button");
  copyBtn.type = "button";
  copyBtn.className = "item";
  copyBtn.innerHTML = "<span>Markdownでコピー</span><small>好きなAIに自分で貼る</small>";
  copyBtn.addEventListener("click", function () {
    var ctx = pageContext();
    close();
    copy("# " + ctx.title + "\n出典: " + ctx.url + "\n\n" + ctx.body).then(function () {
      toast("ページ本文をMarkdownでコピーしました。");
    });
  });
  acts.appendChild(copyBtn);

  providerKeys.forEach(function (key) {
    var p = PROVIDERS[key];
    var b = document.createElement("button");
    b.type = "button";
    b.className = "prov";
    b.setAttribute("aria-pressed", String(key === current));
    b.innerHTML = '<svg viewBox="0 0 24 24">' + p.icon + "</svg>" + p.name;
    b.addEventListener("click", function () {
      current = key;
      localStorage.setItem("askai:provider", key);
      provs.querySelectorAll(".prov").forEach(function (x) { x.setAttribute("aria-pressed", "false"); });
      b.setAttribute("aria-pressed", "true");
      paintLabel();
    });
    provs.appendChild(b);
  });

  function open() { panel.classList.add("open"); btn.setAttribute("aria-expanded", "true"); }
  function close() { panel.classList.remove("open"); btn.setAttribute("aria-expanded", "false"); }
  btn.addEventListener("click", function (e) {
    e.stopPropagation();
    panel.classList.contains("open") ? close() : open();
  });
  document.addEventListener("click", close);
  root.addEventListener("click", function (e) { e.stopPropagation(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") close(); });

  paintLabel();

  function mount() {
    if (cfg.position === "inline" && script && script.parentNode) script.parentNode.insertBefore(host, script);
    else document.body.appendChild(host);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();

  window.askAI = { send: send, prompt: buildPrompt, markdown: function () { return pageContext(); } };
})();
