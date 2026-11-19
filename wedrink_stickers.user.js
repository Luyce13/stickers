// ==UserScript==
// @name         WeDRINK Sticker Printer
// @namespace    wedrink-stickers
// @version      1.1
// @description  Intercepts CISePOS sales and sends item data to the local sticker printer
// @match        https://wedrinkpakistan.cisepos2.com/*
// @grant        GM_xmlhttpRequest
// @connect      localhost
// @connect      127.0.0.1
// @run-at       document-start
// ==/UserScript==

(function () {
    'use strict';

    const STICKER_SERVER = 'http://localhost:9876';

    // ── Extract key fields from multipart form data ──────────
    function parseFormBody(body) {
        const result = {};
        const fields = ['PartyName', 'DailyBillNo', 'CRMCUSCode'];

        if (body instanceof FormData) {
            for (const key of fields) {
                const val = body.get(key);
                if (val !== null && val !== undefined) {
                    result[key] = String(val).trim();
                }
            }
            return result;
        }

        // String body (multipart boundary format)
        if (typeof body === 'string') {
            for (const key of fields) {
                // Match:  name="PartyName"\r\n\r\nAwais Ali\r\n
                const pattern = new RegExp(
                    'name="' + key + '"\\s*\\r?\\n\\r?\\n([^\\r\\n]*)',
                    'i'
                );
                const m = body.match(pattern);
                if (m) result[key] = m[1].trim();
            }
        }

        return result;
    }

    // ── Send sale data to the local Python server ────────────
    function sendToStickerServer(payload) {
        const body = JSON.stringify(payload);

        // Prefer Tampermonkey's cross-origin request
        if (typeof GM_xmlhttpRequest === 'function') {
            GM_xmlhttpRequest({
                method: 'POST',
                url: STICKER_SERVER + '/new-sale',
                headers: { 'Content-Type': 'application/json' },
                data: body,
                timeout: 10000,
                onload: function (resp) {
                    try {
                        const r = JSON.parse(resp.responseText);
                        if (r.status === 'ok') {
                            console.log(
                                '%c[WeDRINK] ✅ ' + r.stickers_printed +
                                ' sticker(s) printed  |  Bill ' + r.bill_no +
                                '  |  Token ' + r.token,
                                'color:green;font-weight:bold'
                            );
                        } else if (r.status === 'skipped') {
                            console.log('[WeDRINK] ⏭️  Skipped: ' + r.reason);
                        } else {
                            console.warn('[WeDRINK] ⚠️  ' + r.reason);
                        }
                    } catch (e) {
                        console.error('[WeDRINK] Bad server response', e);
                    }
                },
                onerror: function () {
                    console.error(
                        '[WeDRINK] ❌ Sticker server unreachable. ' +
                        'Is sticker_server.py running?'
                    );
                },
            });
        } else {
            // Fallback: plain fetch (needs CORS headers from server)
            fetch(STICKER_SERVER + '/new-sale', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: body,
                mode: 'cors',
            })
                .then((r) => r.json())
                .then((r) => console.log('[WeDRINK]', r))
                .catch((e) =>
                    console.error('[WeDRINK] Sticker server error', e)
                );
        }
    }

    // ── Intercept XMLHttpRequest (jQuery / vanilla XHR) ──────
    const _origOpen = XMLHttpRequest.prototype.open;
    const _origSend = XMLHttpRequest.prototype.send;

    XMLHttpRequest.prototype.open = function (method, url /*, async, user, pw */) {
        this.__wd_url = url;
        this.__wd_method = method;
        return _origOpen.apply(this, arguments);
    };

    XMLHttpRequest.prototype.send = function (body) {
        const xhr = this;

        if (
            xhr.__wd_url &&
            typeof xhr.__wd_url === 'string' &&
            xhr.__wd_url.indexOf('insertSale') !== -1
        ) {
            // Grab the customer name etc. from the outgoing form data
            const reqData = parseFormBody(body);

            xhr.addEventListener('load', function () {
                try {
                    if (xhr.status >= 200 && xhr.status < 300) {
                        const resp = JSON.parse(xhr.responseText);
                        if (
                            resp.status === true &&
                            resp.master &&
                            resp.detail
                        ) {
                            console.log(
                                '[WeDRINK] 🧾 Sale detected: ' +
                                resp.master.BillNo
                            );
                            sendToStickerServer({
                                request: reqData,
                                response: resp,
                            });
                        }
                    }
                } catch (e) {
                    console.error('[WeDRINK] XHR parse error', e);
                }
            });
        }

        return _origSend.apply(this, arguments);
    };

    // ── Intercept fetch API (in case CISePOS uses it) ────────
    const _origFetch = window.fetch;
    window.fetch = function (resource, init) {
        const url =
            typeof resource === 'string'
                ? resource
                : resource instanceof Request
                ? resource.url
                : '';

        if (
            url.indexOf('insertSale') !== -1 &&
            init &&
            init.method &&
            init.method.toUpperCase() === 'POST'
        ) {
            const reqData = parseFormBody(init.body);

            return _origFetch.apply(this, arguments).then(function (response) {
                const clone = response.clone();
                clone
                    .json()
                    .then(function (resp) {
                        if (
                            resp.status === true &&
                            resp.master &&
                            resp.detail
                        ) {
                            console.log(
                                '[WeDRINK] 🧾 Sale detected (fetch): ' +
                                resp.master.BillNo
                            );
                            sendToStickerServer({
                                request: reqData,
                                response: resp,
                            });
                        }
                    })
                    .catch(function () {});
                return response;
            });
        }

        return _origFetch.apply(this, arguments);
    };

    // ── Startup banner ───────────────────────────────────────
    console.log(
        '%c[WeDRINK] 🏷️  Sticker printer loaded. Watching for sales…',
        'color:#1e90ff;font-weight:bold'
    );
})();
