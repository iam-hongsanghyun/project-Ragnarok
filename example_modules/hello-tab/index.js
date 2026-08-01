/**
 * Example external tab-module.
 *
 * Contract: export mount(el, ctx) and render into `el`; return a cleanup
 * function. `ctx.apiBase` + `ctx.sessionId` give the module the full Ragnarok
 * backend HTTP API — the same reach a native tab has:
 *
 *   read the model      GET  {apiBase}/api/session/meta?session_id={sessionId}
 *   page a sheet        GET  {apiBase}/api/session/sheet/{name}
 *   submit a solve      POST {apiBase}/api/queue   {sessionId, scenario, options}
 *   read run history    GET  {apiBase}/api/runs
 *   read analytics      GET  {apiBase}/api/runs/{name}/analytics
 */
module.exports = {
  mount(el, ctx) {
    el.innerHTML = [
      '<div style="padding:20px 28px;max-width:720px">',
      '  <h2 style="margin:0 0 6px">Hello Module</h2>',
      '  <p style="color:#64748b;margin:0 0 16px">An external tab-module, mounted like a native tab.</p>',
      '  <pre id="hello-tab-state" style="border:1px solid #e2e8f0;padding:12px;font-size:12px">loading…</pre>',
      '  <button id="hello-tab-refresh" style="padding:6px 14px">Refresh</button>',
      '</div>',
    ].join('\n');

    const state = el.querySelector('#hello-tab-state');
    let disposed = false;

    async function refresh() {
      try {
        const [meta, runs] = await Promise.all([
          fetch(ctx.apiBase + '/api/session/meta?session_id=' + encodeURIComponent(ctx.sessionId)).then((r) => r.json()),
          fetch(ctx.apiBase + '/api/runs').then((r) => r.json()),
        ]);
        if (disposed) return;
        const sheets = (meta.sheets || []).filter((s) => s.rowCount > 0).length;
        state.textContent = [
          'working model : ' + (meta.filename || '(none loaded)'),
          'sheets w/ data: ' + sheets,
          'snapshots     : ' + (meta.snapshotCount || 0),
          'stored runs   : ' + ((runs.runs || []).length),
          '',
          'To solve from a module: POST ' + ctx.apiBase + '/api/queue',
          '  {"sessionId": "' + ctx.sessionId + '", "scenario": {...}, "options": {...}}',
        ].join('\n');
      } catch (err) {
        if (!disposed) state.textContent = 'backend unreachable: ' + err;
      }
    }

    el.querySelector('#hello-tab-refresh').addEventListener('click', refresh);
    refresh();
    return () => { disposed = true; };
  },
};
