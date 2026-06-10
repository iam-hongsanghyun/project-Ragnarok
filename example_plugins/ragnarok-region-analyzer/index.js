/*
 * ragnarok-region-analyzer — 100% frontend plugin (SDK v2)
 * ========================================================
 * Post-run analytics. Reads the solved run result in the browser (no backend)
 * and produces, as TABLES in the Output tab:
 *
 *   1. generation_by_region_total   — generation per region (× carrier if carrier
 *                                      aggregation is on), in the chosen energy unit
 *   2. generation_by_region_hourly  — generation per region per snapshot (MW)
 *   3. regional_flow_total          — net + gross inter-region power (energy unit)
 *   4. regional_flow_hourly         — net inter-region power per snapshot (MW)
 *   (+ capacity_by_region_carrier when carrier aggregation is on — peak-available proxy)
 *
 * Aggregation is driven by two checkboxes:
 *   aggregate_by_region  — group buses into regions (else each bus is its own region)
 *   aggregate_by_carrier — split generation by carrier (else total only)
 *
 * The Output tab renders these as Ragnarok tables. (The host renders plugin
 * output as tables/scalars only — it has no chart surface for plugins — so the
 * hourly tables are shaped snapshot-per-row, ready to copy into a chart.)
 */
'use strict';

function num(v) { var n = typeof v === 'number' ? v : parseFloat(v); return isFinite(n) ? n : 0; }
function round(v, dp) { var f = Math.pow(10, dp == null ? 3 : dp); return Math.round(num(v) * f) / f; }

function normalizeBusMap(v) {
  var out = {};
  if (Array.isArray(v)) {
    v.forEach(function (row) {
      row = row || {};
      var b = row.bus != null ? String(row.bus).trim() : '';
      var r = row.region != null ? String(row.region).trim() : '';
      if (b && r) out[b] = r;
    });
  } else if (v && typeof v === 'object') {
    Object.keys(v).forEach(function (k) { if (v[k] != null && String(v[k]).trim() !== '') out[String(k).trim()] = String(v[k]).trim(); });
  }
  return out;
}

// Embedded bus -> province (official name) for the standard KR model, so a
// numbered nodal bus can be mapped to a region (the run result carries no bus
// province; analyze() is not given the model). A bus whose NAME is already a
// province/region (a region-aggregated model) bypasses this and matches the
// mapping table directly. Buses absent here stay per-bus and are counted in
// meta.unmapped_buses — raise that if you used a different model/numbering.
var BUS_PROVINCE = {"1": "강원특별자치도", "2": "경기도", "3": "경기도", "4": "경기도", "5": "경기도", "6": "인천광역시", "7": "경기도", "8": "경기도", "9": "서울특별시", "10": "경기도", "11": "경기도", "12": "서울특별시", "13": "서울특별시", "14": "서울특별시", "15": "경기도", "16": "경기도", "17": "서울특별시", "18": "서울특별시", "19": "서울특별시", "20": "경기도", "21": "인천광역시", "22": "서울특별시", "23": "서울특별시", "24": "서울특별시", "25": "인천광역시", "26": "경기도", "27": "인천광역시", "28": "경기도", "29": "서울특별시", "30": "서울특별시", "31": "서울특별시", "32": "경기도", "33": "서울특별시", "34": "인천광역시", "35": "경기도", "36": "경기도", "37": "인천광역시", "38": "경기도", "39": "경기도", "40": "경기도", "41": "경기도", "42": "경기도", "43": "경기도", "44": "경기도", "45": "경기도", "46": "경기도", "47": "경기도", "48": "경기도", "49": "경기도", "50": "경기도", "51": "경기도", "52": "충청북도", "53": "충청남도", "54": "충청북도", "55": "충청남도", "56": "충청북도", "57": "충청남도", "58": "충청남도", "59": "충청남도", "60": "충청남도", "61": "충청북도", "62": "충청북도", "63": "충청남도", "64": "세종특별자치시", "65": "강원특별자치도", "66": "강원특별자치도", "67": "강원특별자치도", "68": "강원특별자치도", "69": "강원특별자치도", "70": "강원특별자치도", "71": "강원특별자치도", "72": "강원특별자치도", "73": "강원특별자치도", "74": "강원특별자치도", "75": "강원특별자치도", "76": "강원특별자치도", "77": "강원특별자치도", "78": "강원특별자치도", "79": "강원특별자치도", "80": "강원특별자치도", "81": "충청북도", "82": "경상북도", "83": "충청북도", "84": "충청북도", "85": "경상북도", "86": "경상북도", "87": "경상북도", "88": "경상북도", "89": "경상북도", "90": "경상북도", "91": "충청북도", "92": "충청북도", "93": "경상북도", "94": "경상북도", "95": "경상북도", "96": "충청남도", "97": "충청남도", "98": "대전광역시", "99": "대전광역시", "100": "충청남도", "101": "대전광역시", "102": "충청북도", "103": "충청남도", "104": "충청남도", "105": "충청남도", "106": "충청남도", "107": "전북특별자치도", "108": "전북특별자치도", "109": "전북특별자치도", "110": "전북특별자치도", "111": "전북특별자치도", "112": "전북특별자치도", "113": "전북특별자치도", "114": "전북특별자치도", "115": "전북특별자치도", "116": "전북특별자치도", "117": "전북특별자치도", "118": "전북특별자치도", "119": "전북특별자치도", "120": "전북특별자치도", "121": "전라남도", "122": "전라남도", "123": "전라남도", "124": "전라남도", "125": "전라남도", "126": "광주광역시", "127": "광주광역시", "128": "광주광역시", "129": "전라남도", "130": "전라남도", "131": "전라남도", "132": "전라남도", "133": "전라남도", "134": "전라남도", "135": "전라남도", "136": "전라남도", "137": "전라남도", "138": "전라남도", "139": "전라남도", "140": "전라남도", "141": "전라남도", "142": "전라남도", "143": "전라남도", "144": "전라남도", "145": "전라남도", "146": "대구광역시", "147": "충청북도", "148": "경상북도", "149": "경상북도", "150": "경상북도", "151": "경상북도", "152": "경상북도", "153": "경상북도", "154": "경상북도", "155": "대구광역시", "156": "대구광역시", "157": "대구광역시", "158": "경상북도", "159": "경상북도", "160": "대구광역시", "161": "경상북도", "162": "경상남도", "163": "경상북도", "164": "경상남도", "165": "울산광역시", "166": "울산광역시", "167": "울산광역시", "168": "경상남도", "169": "경상남도", "170": "경상남도", "171": "경상남도", "172": "경상남도", "173": "경상남도", "174": "경상남도", "175": "부산광역시", "176": "경상남도", "177": "경상남도", "178": "경상남도", "179": "부산광역시", "180": "경상남도", "181": "부산광역시", "182": "부산광역시", "183": "경상남도", "184": "부산광역시", "185": "부산광역시", "186": "부산광역시", "187": "부산광역시", "188": "경상남도", "189": "경상남도", "190": "경상남도", "191": "경상남도", "192": "경상남도", "193": "경상남도", "194": "제주특별자치도", "195": "경상북도", "196": "경상북도", "197": "전라남도", "198": "전북특별자치도", "199": "경기도", "200": "경기도", "201": "경기도", "202": "충청남도", "203": "인천광역시", "204": "인천광역시"};

// Approximate centroid (lat, lon) per province official name. Used to place a
// region node on the flow map. A region (province / group) centroid is the mean
// of its member provinces' centroids (see regionCentroid in analyze()).
var PROVINCE_CENTROID = {
  "강원특별자치도": [37.8, 128.2], "경기도": [37.4, 127.2], "경상남도": [35.4, 128.2],
  "경상북도": [36.4, 128.9], "광주광역시": [35.16, 126.85], "대구광역시": [35.87, 128.60],
  "대전광역시": [36.35, 127.38], "부산광역시": [35.18, 129.07], "서울특별시": [37.57, 126.98],
  "세종특별자치시": [36.48, 127.29], "울산광역시": [35.54, 129.31], "인천광역시": [37.46, 126.71],
  "전라남도": [34.9, 126.9], "전북특별자치도": [35.7, 127.1], "제주특별자치도": [33.38, 126.55],
  "충청남도": [36.5, 126.8], "충청북도": [36.8, 127.7]
};

function makeRegionResolver(config, stats) {
  var byRegion = config.aggregate_by_region !== false; // default on
  var busMap = normalizeBusMap(config.bus_region_map);
  var pm = Array.isArray(config.province_mapping) ? config.province_mapping : [];
  var rc = (config.region_column ? String(config.region_column) : '').trim();
  var col = rc === 'province' ? 'short' : rc;
  var pmLookup = {};
  if (byRegion && col) {
    pm.forEach(function (row) {
      row = row || {};
      var val = row[col];
      if (val == null || String(val).trim() === '') return;
      var v = String(val).trim();
      if (row.short) pmLookup[String(row.short).trim()] = v;
      if (row.official) pmLookup[String(row.official).trim()] = v;
    });
  }
  return function (bus) {
    var b = String(bus == null ? '' : bus);
    if (!byRegion) return b;                                  // per-bus
    if (Object.prototype.hasOwnProperty.call(busMap, b)) return busMap[b];
    // 1) bus name is already a province/region (region-aggregated model)
    if (col && Object.prototype.hasOwnProperty.call(pmLookup, b)) return pmLookup[b];
    // 2) numbered bus -> province (embedded) -> region (mapping[region_column])
    var prov = BUS_PROVINCE[b];
    if (prov != null) {
      if (col && Object.prototype.hasOwnProperty.call(pmLookup, prov)) return pmLookup[prov];
      return prov;                                            // region_column blank -> province
    }
    if (stats) stats[b] = true;                               // unmapped: stays per-bus
    return b;
  };
}

function toList(v) {
  if (Array.isArray(v)) return v.map(function (s) { return String(s).trim(); }).filter(Boolean);
  if (typeof v === 'string') return v.split(',').map(function (s) { return s.trim(); }).filter(Boolean);
  return [];
}
function makeFilter(v) {
  var list = toList(v); if (!list.length) return null;
  var set = {}; list.forEach(function (k) { set[k] = true; }); return set;
}
function inc(filter, value) { return filter == null || filter[String(value).trim()] === true; }

// Render an array-of-row-objects as a CSV string. The host shows plugin output
// only as scalar key→value rows (it stringifies arrays to "[object Object]"),
// so each result table is delivered as one CSV cell — readable and copyable
// straight into a spreadsheet for charting.
function csvFromRows(rows) {
  if (!Array.isArray(rows) || rows.length === 0) return '(none)';
  var header = Object.keys(rows[0]);
  var lines = [header.join(',')];
  for (var i = 0; i < rows.length; i++) {
    var r = rows[i];
    lines.push(header.map(function (h) { var v = r[h]; return v == null ? '' : String(v); }).join(','));
  }
  return lines.join('\n');
}

// Snapshot labels from any available series (all series share the snapshot index).
function snapshotLabels(details) {
  var src = null;
  var g = details.generators || {};
  var keys = Object.keys(g);
  for (var i = 0; i < keys.length; i++) { if (Array.isArray(g[keys[i]].outputSeries) && g[keys[i]].outputSeries.length) { src = g[keys[i]].outputSeries; break; } }
  if (!src) {
    var b = details.branches || {}; var bk = Object.keys(b);
    for (var j = 0; j < bk.length; j++) { if (Array.isArray(b[bk[j]].flowSeries) && b[bk[j]].flowSeries.length) { src = b[bk[j]].flowSeries; break; } }
  }
  if (!src) return [];
  return src.map(function (p) { return p.label != null ? String(p.label) : String(p.timestamp || ''); });
}

module.exports = {
  analyze: function analyze(result, config) {
    config = config || {};
    if (!result || typeof result !== 'object' || !result.assetDetails) {
      return { note: 'No run result yet — run the model in Ragnarok first.' };
    }
    var details = result.assetDetails;
    var gens = details.generators || {};
    var branches = details.branches || {};

    var byCarrier = config.aggregate_by_carrier !== false; // default on
    var weight = (config.snapshot_weight != null && config.snapshot_weight !== '')
      ? num(config.snapshot_weight)
      : (result.runMeta && result.runMeta.snapshotWeight != null ? num(result.runMeta.snapshotWeight) : 1);
    if (!(weight > 0)) weight = 1;

    var unit = String(config.energy_unit || 'GWh').toUpperCase();
    var scale = unit === 'MWH' ? 1 : unit === 'TWH' ? 1e-6 : 1e-3;
    var unitLabel = unit === 'MWH' ? 'MWh' : unit === 'TWH' ? 'TWh' : 'GWh';
    var E = function (mwh) { return round(mwh * scale, 4); };

    var unmappedBuses = {};
    var regionOf = makeRegionResolver(config, unmappedBuses);
    var rf = makeFilter(config.regions);
    var cf = makeFilter(config.carriers);
    var maxHours = (config.max_hours != null && num(config.max_hours) > 0) ? Math.floor(num(config.max_hours)) : Infinity;

    var labels = snapshotLabels(details);
    var nSnap = labels.length;
    var hoursShown = Math.min(nSnap, maxHours);

    // ── Generation: totals (energy) + capacity proxy, grouped by region[/carrier]
    var genTotal = {};      // region -> carrier -> MWh
    var capTotal = {};      // region -> carrier -> MW (peak available proxy)
    var carrierSet = {}, regionGenSet = {};
    var hourlyGenByRegion = {}; // region -> [MW per snapshot]

    Object.keys(gens).forEach(function (name) {
      var g = gens[name] || {};
      var region = regionOf(g.bus);
      var carrier = byCarrier ? String(g.carrier == null ? '(none)' : g.carrier) : 'all';
      if (!inc(rf, region)) return;
      if (byCarrier && !inc(cf, g.carrier)) return;

      var out = g.outputSeries || [];
      var mwh = 0; for (var i = 0; i < out.length; i++) mwh += Math.max(num(out[i].output), 0) * weight;
      if (!genTotal[region]) genTotal[region] = {};
      genTotal[region][carrier] = (genTotal[region][carrier] || 0) + mwh;
      carrierSet[carrier] = true; regionGenSet[region] = true;

      // capacity proxy = peak available MW
      var avail = g.availableSeries || []; var cap = 0;
      for (var k = 0; k < avail.length; k++) { var a = num(avail[k].available); if (a > cap) cap = a; }
      if (!capTotal[region]) capTotal[region] = {};
      capTotal[region][carrier] = (capTotal[region][carrier] || 0) + cap;

      // hourly generation by region (MW, summed over carriers)
      if (!hourlyGenByRegion[region]) hourlyGenByRegion[region] = new Array(nSnap).fill(0);
      for (var t = 0; t < out.length && t < nSnap; t++) hourlyGenByRegion[region][t] += Math.max(num(out[t].output), 0);
    });

    var carriers = Object.keys(carrierSet).sort();
    var regions = Object.keys(regionGenSet).sort();

    // 1. generation_by_region_total
    var generation_by_region_total;
    if (byCarrier) {
      generation_by_region_total = regions.map(function (r) {
        var rowOut = { region: r }, tot = 0;
        carriers.forEach(function (c) { var mwh = (genTotal[r] && genTotal[r][c]) || 0; rowOut[c] = E(mwh); tot += mwh; });
        rowOut['Total_' + unitLabel] = E(tot);
        return rowOut;
      });
    } else {
      generation_by_region_total = regions.map(function (r) {
        return { region: r, ['generation_' + unitLabel]: E((genTotal[r] && genTotal[r].all) || 0) };
      });
    }

    // capacity_by_region_carrier (only when carrier aggregation on)
    var capacity_by_region_carrier = null;
    if (byCarrier) {
      capacity_by_region_carrier = regions.map(function (r) {
        var rowOut = { region: r }, tot = 0;
        carriers.forEach(function (c) { var mw = (capTotal[r] && capTotal[r][c]) || 0; rowOut[c] = round(mw, 2); tot += mw; });
        rowOut.Total_MW = round(tot, 2);
        return rowOut;
      });
    }

    // 2. generation_by_region_hourly (MW)
    var generation_by_region_hourly = [];
    for (var h = 0; h < hoursShown; h++) {
      var row = { snapshot: labels[h] };
      regions.forEach(function (r) { row[r] = round(hourlyGenByRegion[r] ? hourlyGenByRegion[r][h] : 0, 3); });
      generation_by_region_hourly.push(row);
    }

    // ── Inter-region flows (lines + links). p0 = MW into branch at bus0.
    var pairNetE = {}, pairGrossE = {};         // energy (MWh) per normalised pair
    var pairHourly = {};                         // "A→B" key -> [MW per snapshot], signed to a<=b then flipped on display
    var pairOrder = {};                          // key -> [a,b]
    Object.keys(branches).forEach(function (name) {
      var br = branches[name] || {};
      var rA = regionOf(br.bus0), rB = regionOf(br.bus1);
      if (rA === rB) return;
      if (!inc(rf, rA) || !inc(rf, rB)) return;
      var fs = br.flowSeries || [];
      var a = rA, b = rB, sign = 1;
      if (rA > rB) { a = rB; b = rA; sign = -1; }
      var key = a + '||' + b;
      pairOrder[key] = [a, b];
      var netMwh = 0, grossMwh = 0;
      if (!pairHourly[key]) pairHourly[key] = new Array(nSnap).fill(0);
      for (var i = 0; i < fs.length; i++) {
        var p0 = num(fs[i].p0) * sign;          // + means a→b
        netMwh += p0 * weight; grossMwh += Math.abs(num(fs[i].p0)) * weight;
        if (i < nSnap) pairHourly[key][i] += p0;
      }
      pairNetE[key] = (pairNetE[key] || 0) + netMwh;
      pairGrossE[key] = (pairGrossE[key] || 0) + grossMwh;
    });

    // 3. regional_flow_total
    var flowsAll = Object.keys(pairNetE).map(function (key) {
      var ab = pairOrder[key], net = pairNetE[key];
      var from = net >= 0 ? ab[0] : ab[1], to = net >= 0 ? ab[1] : ab[0];
      return { from: from, to: to, ['net_' + unitLabel]: E(Math.abs(net)), ['gross_' + unitLabel]: E(pairGrossE[key] || 0) };
    }).sort(function (x, y) { return y['net_' + unitLabel] - x['net_' + unitLabel]; });
    var topFlows = (config.top_flows != null && num(config.top_flows) > 0) ? num(config.top_flows) : flowsAll.length;
    var regional_flow_total = flowsAll.slice(0, topFlows);

    // 4. regional_flow_hourly (MW); column header A→B is the a<=b direction (+ = A→B)
    var flowKeys = Object.keys(pairHourly);
    var regional_flow_hourly = [];
    for (var fh = 0; fh < hoursShown; fh++) {
      var frow = { snapshot: labels[fh] };
      flowKeys.forEach(function (key) { var ab = pairOrder[key]; frow[ab[0] + '→' + ab[1]] = round(pairHourly[key][fh], 3); });
      regional_flow_hourly.push(frow);
    }

    // System + carrier totals
    var totalGen = 0; var carrierTotal = {};
    regions.forEach(function (r) { Object.keys(genTotal[r] || {}).forEach(function (c) { totalGen += genTotal[r][c]; carrierTotal[c] = (carrierTotal[c] || 0) + genTotal[r][c]; }); });
    var carrier_totals = Object.keys(carrierTotal).sort().map(function (c) {
      return { carrier: c, ['energy_' + unitLabel]: E(carrierTotal[c]), share_pct: round(totalGen > 0 ? carrierTotal[c] / totalGen * 100 : 0, 2) };
    }).sort(function (x, y) { return y['energy_' + unitLabel] - x['energy_' + unitLabel]; });

    // ── Selected region for the per-region deep-dive charts ────────────────
    // Use the configured region if it exists in the result; otherwise the
    // highest-generation region (so the charts are never empty).
    var regionTotal = function (r) { var t = 0; Object.keys(genTotal[r] || {}).forEach(function (c) { t += genTotal[r][c]; }); return t; };
    var selectedRegion = '';
    // The region selector is one of several gated fields — pick the one that
    // matches the active region_column so its values match the actual regions.
    var rcSel = (config.region_column ? String(config.region_column) : 'province').trim();
    var selField = {
      province: 'chart_region_province', group1: 'chart_region_group1',
      group2: 'chart_region_group2', group3: 'chart_region_group3',
      singlenode: 'chart_region_singlenode',
    }[rcSel] || 'chart_region_province';
    var wantedRegion = String(config[selField] || config.chart_region || '').trim();
    if (wantedRegion && regionGenSet[wantedRegion]) {
      selectedRegion = wantedRegion;
    } else {
      var bestTot = -1;
      regions.forEach(function (r) { var t = regionTotal(r); if (t > bestTot) { bestTot = t; selectedRegion = r; } });
    }

    // Second pass: hourly generation (MW) by carrier for the selected region.
    var selHourly = {};                          // carrier -> [MW per snapshot]
    if (selectedRegion) {
      Object.keys(gens).forEach(function (name) {
        var g = gens[name] || {};
        if (regionOf(g.bus) !== selectedRegion) return;
        if (byCarrier && !inc(cf, g.carrier)) return;
        var carrier = byCarrier ? String(g.carrier == null ? '(none)' : g.carrier) : 'all';
        var out = g.outputSeries || [];
        if (!selHourly[carrier]) selHourly[carrier] = new Array(nSnap).fill(0);
        for (var t = 0; t < out.length && t < nSnap; t++) selHourly[carrier][t] += Math.max(num(out[t].output), 0);
      });
    }
    var selCarriers = Object.keys(selHourly).sort();

    // ── Chart specs (PluginChartSpec: kind line|area|bar|donut) ─────────────
    var donutSystem = {
      kind: 'donut', description: 'System generation by carrier (' + unitLabel + ')',
      slices: carriers.map(function (c) { return { label: c, value: E(carrierTotal[c] || 0) }; }).filter(function (s) { return s.value > 0; }),
    };
    var barByRegion = {
      kind: 'bar', stacked: true, description: 'Generation by region (' + unitLabel + ')',
      xAxisTitle: 'region', yAxisTitle: unitLabel,
      series: carriers.map(function (c) { return { key: c }; }),
      rows: regions.map(function (r) { var row = { label: r }; carriers.forEach(function (c) { row[c] = E((genTotal[r] && genTotal[r][c]) || 0); }); return row; }),
    };
    var donutRegion = {
      kind: 'donut', description: 'Carrier mix — ' + selectedRegion + ' (' + unitLabel + ')',
      slices: carriers.map(function (c) { return { label: c, value: E((genTotal[selectedRegion] && genTotal[selectedRegion][c]) || 0) }; }).filter(function (s) { return s.value > 0; }),
    };
    var areaRegion = {
      kind: 'area', stacked: true, description: 'Hourly generation — ' + selectedRegion + ' (MW, first ' + hoursShown + ' of ' + nSnap + ' h)',
      xAxisTitle: 'snapshot', yAxisTitle: 'MW',
      series: selCarriers.map(function (c) { return { key: c }; }),
      rows: (function () { var rows = []; for (var h = 0; h < hoursShown; h++) { var row = { label: labels[h] }; selCarriers.forEach(function (c) { row[c] = round(selHourly[c][h], 3); }); rows.push(row); } return rows; })(),
    };
    var flowBar = {
      kind: 'bar', description: 'Inter-region net flow (' + unitLabel + ')', yAxisTitle: unitLabel,
      series: [{ key: 'net', label: 'net ' + unitLabel }],
      rows: regional_flow_total.map(function (f) { return { label: f.from + '→' + f.to, net: f['net_' + unitLabel] }; }),
    };

    // Region-flow MAP: place each region at the mean centroid of its member
    // provinces, size the node by generation, and draw net flows as lines.
    var PM2 = Array.isArray(config.province_mapping) ? config.province_mapping : [];
    var rcol = (config.region_column ? String(config.region_column) : '').trim();
    var ccol = rcol === 'province' ? 'short' : rcol;
    var officialsByRegion = {};
    PM2.forEach(function (row) {
      if (!row) return;
      var official = row.official != null ? String(row.official).trim() : '';
      if (!official) return;
      var regionVal = (ccol && row[ccol] != null && String(row[ccol]).trim() !== '')
        ? String(row[ccol]).trim()
        : (row.short != null ? String(row.short).trim() : '');
      if (!regionVal) return;
      (officialsByRegion[regionVal] = officialsByRegion[regionVal] || []).push(official);
    });
    var regionCentroid = function (region) {
      if (PROVINCE_CENTROID[region]) return PROVINCE_CENTROID[region];   // region IS a province
      var offs = officialsByRegion[region];
      if (!offs || !offs.length) return null;
      var lat = 0, lon = 0, n = 0;
      offs.forEach(function (o) { var c = PROVINCE_CENTROID[o]; if (c) { lat += c[0]; lon += c[1]; n++; } });
      return n ? [lat / n, lon / n] : null;
    };
    var mapNodes = [], nodeHas = {};
    regions.forEach(function (r) {
      var c = regionCentroid(r);
      if (!c) return;
      nodeHas[r] = true;
      var mix = carriers.map(function (cc) {
        return { label: cc, value: E((genTotal[r] && genTotal[r][cc]) || 0) };
      }).filter(function (s) { return s.value > 0; });
      mapNodes.push({ id: r, label: r, lat: c[0], lon: c[1], value: E(regionTotal(r)), mix: mix });
    });
    var mapEdges = regional_flow_total
      .filter(function (f) { return nodeHas[f.from] && nodeHas[f.to]; })
      .map(function (f) {
        var v = f['net_' + unitLabel];
        return { from: f.from, to: f.to, value: v, label: f.from + ' → ' + f.to + ': ' + v + ' ' + unitLabel };
      });
    var flowMap = {
      kind: 'map',
      description: 'Generation mix by node (' + unitLabel + ') — pie = carrier mix, size = total generation, line width = net inter-region flow',
      nodes: mapNodes, edges: mapEdges,
    };

    // ── Output ──────────────────────────────────────────────────────────────
    // Charts are emitted as PluginChartSpec objects; the host detects them
    // (format: chart) and draws them with its own chart components. Arrays of
    // row objects render as tables. Scalars render as key→value rows.
    var grouping = (config.aggregate_by_region === false)
      ? 'per-bus'
      : (config.region_column ? config.region_column : 'identity (bus = region)');

    // Stash the aggregated tables as a single CSV on `window` so the
    // "Download aggregated (CSV)" action button can export them. The action
    // hook runs in a fresh module instance (loadPluginModule is not cached),
    // so a module-level variable would not survive — `window` is shared.
    var aggSections = [
      { title: 'Generation by region (' + unitLabel + ')', rows: generation_by_region_total },
      capacity_by_region_carrier ? { title: 'Capacity by region (MW)', rows: capacity_by_region_carrier } : null,
      { title: 'Carrier totals (' + unitLabel + ')', rows: carrier_totals },
      { title: 'Regional flow (' + unitLabel + ')', rows: regional_flow_total },
    ].filter(Boolean);
    var aggParts = [];
    aggSections.forEach(function (s) {
      if (!s.rows || !s.rows.length) return;
      aggParts.push('# ' + s.title);
      aggParts.push(csvFromRows(s.rows));
      aggParts.push('');
    });
    if (typeof window !== 'undefined') {
      window.__rra_export = {
        filename: 'region_analysis_' + grouping + '_' + unitLabel + '.csv',
        csv: aggParts.join('\n'),
      };
    }

    var data = {};
    data['Settings'] =
      'group by=' + grouping + ', regions=' + regions.length +
      ', unit=' + unitLabel + ', weight=' + round(weight, 4) + 'h' +
      (Object.keys(unmappedBuses).length ? ', UNMAPPED buses=' + Object.keys(unmappedBuses).length + ' (kept per-bus — check model/bus numbering)' : '');
    data['Total generation (' + unitLabel + ')'] = E(totalGen);

    data['Carrier mix (system)'] = donutSystem;
    data['Generation by region'] = barByRegion;
    data['Carrier mix — ' + selectedRegion] = donutRegion;
    data['Hourly generation — ' + selectedRegion] = areaRegion;
    data['Inter-region net flow'] = flowBar;
    data['Inter-region flow map'] = flowMap;

    // Underlying tables (rendered as tables by the host).
    data['Generation by region — table (' + unitLabel + ')'] = generation_by_region_total;
    if (capacity_by_region_carrier) data['Capacity by region — table (MW)'] = capacity_by_region_carrier;
    data['Carrier totals — table (' + unitLabel + ')'] = carrier_totals;
    data['Regional flow — table (' + unitLabel + ')'] = regional_flow_total;

    return data;
  },

  // Action hook (button in the Input tab): download the aggregated tables that
  // the last analyze() run stashed on `window` as a single CSV file.
  downloadAggregated: function downloadAggregated(config) {
    var store = (typeof window !== 'undefined') ? window.__rra_export : null;
    if (!store || !store.csv) {
      return { ok: false, message: 'Nothing to export yet — run the model and open the Output tab first.' };
    }
    try {
      var blob = new Blob([store.csv], { type: 'text/csv;charset=utf-8;' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = store.filename || 'region_analysis.csv';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
      return { ok: true, message: 'Downloaded ' + (store.filename || 'region_analysis.csv') };
    } catch (e) {
      return { ok: false, message: 'Download failed: ' + (e && e.message ? e.message : String(e)) };
    }
  },
};
