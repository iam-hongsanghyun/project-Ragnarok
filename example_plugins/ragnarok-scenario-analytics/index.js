/*
 * ragnarok-scenario-analytics — 100% frontend plugin (SDK v2)
 * ===========================================================
 * Post-run, system-level analytics for the 11th-Basic-Plan alternative-scenario
 * study. Reads the solved run result in the browser (no backend) and emits, for
 * the CURRENT run, the charts + numbers the research figures need:
 *
 *   A. Generation & capacity mix  — generation donut, installed-capacity bar,
 *                                    capacity-by-year stacked bar, RE share.
 *   B. Hourly dispatch + SMP       — stacked-area dispatch over a window, system
 *                                    load line, SMP line, zero-price-hours %.
 *   C. Emissions vs targets        — cumulative CO2 area, CO2-vs-NDC bar,
 *                                    emission factor, emissions-by-carrier table.
 *   D. Regional flows + adequacy   — inter-region flow map (carrier-mix pies),
 *                                    peak demand & reserve margin, load-duration.
 *
 * Single solved run at a time (no scenario library). Installed capacity comes
 * from the run's embedded network (`result.outputs.static.generators`), so no
 * own server is needed. Region helpers + flow map reuse the region-analyzer.
 */
'use strict';

function num(v) { var n = typeof v === 'number' ? v : parseFloat(v); return isFinite(n) ? n : 0; }
function round(v, dp) { var f = Math.pow(10, dp == null ? 3 : dp); return Math.round(num(v) * f) / f; }

// Carriers treated as renewable for the "renewable share" KPI.
var RE_CARRIERS = { solar: true, wind: true, hydro: true, bio: true };

// Embedded bus -> province (official name) for the standard KR model, so a
// numbered nodal bus maps to a region (run result carries no bus province).
var BUS_PROVINCE = {"1": "강원특별자치도", "2": "경기도", "3": "경기도", "4": "경기도", "5": "경기도", "6": "인천광역시", "7": "경기도", "8": "경기도", "9": "서울특별시", "10": "경기도", "11": "경기도", "12": "서울특별시", "13": "서울특별시", "14": "서울특별시", "15": "경기도", "16": "경기도", "17": "서울특별시", "18": "서울특별시", "19": "서울특별시", "20": "경기도", "21": "인천광역시", "22": "서울특별시", "23": "서울특별시", "24": "서울특별시", "25": "인천광역시", "26": "경기도", "27": "인천광역시", "28": "경기도", "29": "서울특별시", "30": "서울특별시", "31": "서울특별시", "32": "경기도", "33": "서울특별시", "34": "인천광역시", "35": "경기도", "36": "경기도", "37": "인천광역시", "38": "경기도", "39": "경기도", "40": "경기도", "41": "경기도", "42": "경기도", "43": "경기도", "44": "경기도", "45": "경기도", "46": "경기도", "47": "경기도", "48": "경기도", "49": "경기도", "50": "경기도", "51": "경기도", "52": "충청북도", "53": "충청남도", "54": "충청북도", "55": "충청남도", "56": "충청북도", "57": "충청남도", "58": "충청남도", "59": "충청남도", "60": "충청남도", "61": "충청북도", "62": "충청북도", "63": "충청남도", "64": "세종특별자치시", "65": "강원특별자치도", "66": "강원특별자치도", "67": "강원특별자치도", "68": "강원특별자치도", "69": "강원특별자치도", "70": "강원특별자치도", "71": "강원특별자치도", "72": "강원특별자치도", "73": "강원특별자치도", "74": "강원특별자치도", "75": "강원특별자치도", "76": "강원특별자치도", "77": "강원특별자치도", "78": "강원특별자치도", "79": "강원특별자치도", "80": "강원특별자치도", "81": "충청북도", "82": "경상북도", "83": "충청북도", "84": "충청북도", "85": "경상북도", "86": "경상북도", "87": "경상북도", "88": "경상북도", "89": "경상북도", "90": "경상북도", "91": "충청북도", "92": "충청북도", "93": "경상북도", "94": "경상북도", "95": "경상북도", "96": "충청남도", "97": "충청남도", "98": "대전광역시", "99": "대전광역시", "100": "충청남도", "101": "대전광역시", "102": "충청북도", "103": "충청남도", "104": "충청남도", "105": "충청남도", "106": "충청남도", "107": "전북특별자치도", "108": "전북특별자치도", "109": "전북특별자치도", "110": "전북특별자치도", "111": "전북특별자치도", "112": "전북특별자치도", "113": "전북특별자치도", "114": "전북특별자치도", "115": "전북특별자치도", "116": "전북특별자치도", "117": "전북특별자치도", "118": "전북특별자치도", "119": "전북특별자치도", "120": "전북특별자치도", "121": "전라남도", "122": "전라남도", "123": "전라남도", "124": "전라남도", "125": "전라남도", "126": "광주광역시", "127": "광주광역시", "128": "광주광역시", "129": "전라남도", "130": "전라남도", "131": "전라남도", "132": "전라남도", "133": "전라남도", "134": "전라남도", "135": "전라남도", "136": "전라남도", "137": "전라남도", "138": "전라남도", "139": "전라남도", "140": "전라남도", "141": "전라남도", "142": "전라남도", "143": "전라남도", "144": "전라남도", "145": "전라남도", "146": "대구광역시", "147": "충청북도", "148": "경상북도", "149": "경상북도", "150": "경상북도", "151": "경상북도", "152": "경상북도", "153": "경상북도", "154": "경상북도", "155": "대구광역시", "156": "대구광역시", "157": "대구광역시", "158": "경상북도", "159": "경상북도", "160": "대구광역시", "161": "경상북도", "162": "경상남도", "163": "경상북도", "164": "경상남도", "165": "울산광역시", "166": "울산광역시", "167": "울산광역시", "168": "경상남도", "169": "경상남도", "170": "경상남도", "171": "경상남도", "172": "경상남도", "173": "경상남도", "174": "경상남도", "175": "부산광역시", "176": "경상남도", "177": "경상남도", "178": "경상남도", "179": "부산광역시", "180": "경상남도", "181": "부산광역시", "182": "부산광역시", "183": "경상남도", "184": "부산광역시", "185": "부산광역시", "186": "부산광역시", "187": "부산광역시", "188": "경상남도", "189": "경상남도", "190": "경상남도", "191": "경상남도", "192": "경상남도", "193": "경상남도", "194": "제주특별자치도", "195": "경상북도", "196": "경상북도", "197": "전라남도", "198": "전북특별자치도", "199": "경기도", "200": "경기도", "201": "경기도", "202": "충청남도", "203": "인천광역시", "204": "인천광역시"};

var PROVINCE_CENTROID = {
  "강원특별자치도": [37.8, 128.2], "경기도": [37.4, 127.2], "경상남도": [35.4, 128.2],
  "경상북도": [36.4, 128.9], "광주광역시": [35.16, 126.85], "대구광역시": [35.87, 128.60],
  "대전광역시": [36.35, 127.38], "부산광역시": [35.18, 129.07], "서울특별시": [37.57, 126.98],
  "세종특별자치시": [36.48, 127.29], "울산광역시": [35.54, 129.31], "인천광역시": [37.46, 126.71],
  "전라남도": [34.9, 126.9], "전북특별자치도": [35.7, 127.1], "제주특별자치도": [33.38, 126.55],
  "충청남도": [36.5, 126.8], "충청북도": [36.8, 127.7]
};

function makeRegionResolver(config) {
  var byRegion = config.aggregate_by_region !== false; // default on
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
    if (!byRegion) return b;
    if (col && Object.prototype.hasOwnProperty.call(pmLookup, b)) return pmLookup[b];
    var prov = BUS_PROVINCE[b];
    if (prov != null) {
      if (col && Object.prototype.hasOwnProperty.call(pmLookup, prov)) return pmLookup[prov];
      return prov;
    }
    return b;
  };
}

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

function snapshotLabels(details) {
  var g = details.generators || {};
  var keys = Object.keys(g);
  for (var i = 0; i < keys.length; i++) {
    if (Array.isArray(g[keys[i]].outputSeries) && g[keys[i]].outputSeries.length) {
      return g[keys[i]].outputSeries.map(function (p) { return p.label != null ? String(p.label) : String(p.timestamp || ''); });
    }
  }
  return [];
}

// Installed capacity (MW) by carrier from the run's embedded network, and an
// optional capacity-by-build-year stacked-bar dataset (build_year ≤ y < close_year;
// missing build_year = "always built", missing close_year = "never closes").
function capacityFromOutputs(result, gens) {
  var statics = (result.outputs && result.outputs.static && result.outputs.static.generators) || {};
  var names = Object.keys(statics);
  var capByCarrier = {};            // carrier -> MW
  var fleet = [];                   // {cap, carrier, by, cy}
  names.forEach(function (name) {
    var s = statics[name] || {};
    var capRaw = (s.p_nom_opt != null && s.p_nom_opt !== '') ? s.p_nom_opt : s.p_nom;
    var cap = num(capRaw);
    var carrier = String((s.carrier != null ? s.carrier : (gens[name] && gens[name].carrier)) || 'other').trim() || 'other';
    capByCarrier[carrier] = (capByCarrier[carrier] || 0) + cap;
    var by = (s.build_year != null && s.build_year !== '') ? Math.round(num(s.build_year)) : null;
    var cy = (s.close_year != null && s.close_year !== '') ? Math.round(num(s.close_year)) : null;
    fleet.push({ cap: cap, carrier: carrier, by: by, cy: cy });
  });
  var totalCapMW = 0;
  Object.keys(capByCarrier).forEach(function (c) { totalCapMW += capByCarrier[c]; });
  return { capByCarrier: capByCarrier, totalCapMW: totalCapMW, fleet: fleet, hasAny: names.length > 0 };
}

function capacityByYearRows(fleet, carriers) {
  var finiteBuild = fleet.filter(function (r) { return r.by != null; }).map(function (r) { return r.by; });
  if (!finiteBuild.length) return null;                 // no build_year info → skip
  var finiteClose = fleet.filter(function (r) { return r.cy != null; }).map(function (r) { return r.cy; });
  var start = Math.min.apply(null, finiteBuild);
  var end = Math.max.apply(null, finiteBuild.concat(finiteClose.length ? finiteClose : finiteBuild));
  if (end < start) end = start;
  if (end - start > 60) end = start + 60;               // guard absurd close years
  var rows = [];
  for (var y = start; y <= end; y++) {
    var row = { label: String(y) };
    carriers.forEach(function (c) { row[c] = 0; });
    fleet.forEach(function (r) {
      var built = (r.by == null) || (r.by <= y);
      var open = (r.cy == null) || (y < r.cy);
      if (built && open && Object.prototype.hasOwnProperty.call(row, r.carrier)) {
        row[r.carrier] = round(row[r.carrier] + r.cap / 1000, 3);   // GW
      }
    });
    rows.push(row);
  }
  return rows;
}

module.exports = {
  analyze: function analyze(result, config) {
    config = config || {};
    if (!result || typeof result !== 'object' || !result.assetDetails) {
      return { note: 'No run result yet — run the model in Ragnarok first.' };
    }
    var details = result.assetDetails;
    var gens = details.generators || {};
    var buses = details.buses || {};
    var branches = details.branches || {};

    var weight = (result.runMeta && result.runMeta.snapshotWeight != null) ? num(result.runMeta.snapshotWeight) : 1;
    if (!(weight > 0)) weight = 1;

    var unit = String(config.energy_unit || 'TWh').toUpperCase();
    var scale = unit === 'MWH' ? 1 : unit === 'TWH' ? 1e-6 : 1e-3;
    var unitLabel = unit === 'MWH' ? 'MWh' : unit === 'TWH' ? 'TWh' : 'GWh';
    var E = function (mwh) { return round(mwh * scale, 4); };

    var labels = snapshotLabels(details);
    var nSnap = labels.length;
    var start = Math.max(0, Math.floor(num(config.dispatch_start)));
    var hours = (config.dispatch_hours != null && num(config.dispatch_hours) > 0) ? Math.floor(num(config.dispatch_hours)) : 168;
    var winEnd = Math.min(nSnap, start + hours);

    // ── Generation by carrier: energy total + hourly (for dispatch & mix) ────
    var carrierEnergy = {};                 // carrier -> MWh
    var carrierHourly = {};                 // carrier -> [MW per snapshot]
    var curtailRE = 0, outputRE = 0;        // for renewable curtailment %
    var totalGenMWh = 0;
    Object.keys(gens).forEach(function (name) {
      var g = gens[name] || {};
      var carrier = String(g.carrier == null ? 'other' : g.carrier).trim() || 'other';
      var out = g.outputSeries || [];
      if (!carrierHourly[carrier]) carrierHourly[carrier] = new Array(nSnap).fill(0);
      var mwh = 0;
      for (var i = 0; i < out.length; i++) {
        var mw = Math.max(num(out[i].output), 0);
        mwh += mw * weight;
        if (i < nSnap) carrierHourly[carrier][i] += mw;
      }
      carrierEnergy[carrier] = (carrierEnergy[carrier] || 0) + mwh;
      totalGenMWh += mwh;
      if (RE_CARRIERS[carrier]) {
        var cur = g.curtailmentSeries || [];
        for (var k = 0; k < cur.length; k++) curtailRE += Math.max(num(cur[k].curtailment), 0) * weight;
        outputRE += mwh;
      }
    });
    var carriers = Object.keys(carrierEnergy).sort();

    // ── System load per snapshot (sum of bus loads) ──────────────────────────
    var loadHourly = new Array(nSnap).fill(0);
    Object.keys(buses).forEach(function (name) {
      var ns = (buses[name] || {}).netSeries || [];
      for (var t = 0; t < ns.length && t < nSnap; t++) loadHourly[t] += num(ns[t].load);
    });
    var peakDemand = 0;
    for (var p = 0; p < nSnap; p++) if (loadHourly[p] > peakDemand) peakDemand = loadHourly[p];

    // ── SMP + emissions system series ────────────────────────────────────────
    var smp = (result.systemPriceSeries || []).map(function (x) { return num(x.value); });
    var smpAvg = smp.length ? round(smp.reduce(function (a, b) { return a + b; }, 0) / smp.length, 1) : 0;
    var zeroHours = smp.filter(function (v) { return v <= 0.5; }).length;
    var zeroPricePct = smp.length ? round(zeroHours / smp.length * 100, 1) : 0;

    var emisSeries = (result.systemEmissionsSeries || []).map(function (x) { return num(x.value) * weight; }); // tCO2/snapshot
    var totalCO2t = emisSeries.reduce(function (a, b) { return a + b; }, 0);
    var totalCO2Mt = round(totalCO2t / 1e6, 3);
    var emissionFactor = totalGenMWh > 0 ? round(totalCO2t / totalGenMWh * 1000, 1) : 0; // gCO2/kWh

    // ── Installed capacity (from embedded network) ───────────────────────────
    var cap = capacityFromOutputs(result, gens);
    var capCarriers = Object.keys(cap.capByCarrier).sort();
    var reserveMargin = peakDemand > 0 ? round((cap.totalCapMW - peakDemand) / peakDemand * 100, 1) : 0;

    // Renewable share %
    var reMWh = 0;
    Object.keys(carrierEnergy).forEach(function (c) { if (RE_CARRIERS[c]) reMWh += carrierEnergy[c]; });
    var rePct = totalGenMWh > 0 ? round(reMWh / totalGenMWh * 100, 1) : 0;
    var curtailPct = (outputRE + curtailRE) > 0 ? round(curtailRE / (outputRE + curtailRE) * 100, 2) : 0;

    // ── Inter-region flows (reuse region resolver + centroids) ───────────────
    var regionOf = makeRegionResolver(config);
    var genTotalByRegion = {};   // region -> carrier -> MWh
    var regionSet = {};
    Object.keys(gens).forEach(function (name) {
      var g = gens[name] || {};
      var region = regionOf(g.bus);
      var carrier = String(g.carrier == null ? 'other' : g.carrier).trim() || 'other';
      regionSet[region] = true;
      var out = g.outputSeries || [];
      var mwh = 0; for (var i = 0; i < out.length; i++) mwh += Math.max(num(out[i].output), 0) * weight;
      if (!genTotalByRegion[region]) genTotalByRegion[region] = {};
      genTotalByRegion[region][carrier] = (genTotalByRegion[region][carrier] || 0) + mwh;
    });
    var pairNet = {}, pairOrder = {};
    Object.keys(branches).forEach(function (name) {
      var br = branches[name] || {};
      var rA = regionOf(br.bus0), rB = regionOf(br.bus1);
      if (rA === rB) return;
      var a = rA, b = rB, sign = 1;
      if (rA > rB) { a = rB; b = rA; sign = -1; }
      var key = a + '||' + b;
      pairOrder[key] = [a, b];
      var fs = br.flowSeries || [], netMwh = 0;
      for (var i = 0; i < fs.length; i++) netMwh += num(fs[i].p0) * sign * weight;
      pairNet[key] = (pairNet[key] || 0) + netMwh;
    });
    var flowRows = Object.keys(pairNet).map(function (key) {
      var ab = pairOrder[key], net = pairNet[key];
      var from = net >= 0 ? ab[0] : ab[1], to = net >= 0 ? ab[1] : ab[0];
      return { from: from, to: to, ['net_' + unitLabel]: E(Math.abs(net)) };
    }).sort(function (x, y) { return y['net_' + unitLabel] - x['net_' + unitLabel]; });

    // Region centroids → map nodes (carrier-mix pie) + edges (net flow)
    var PM2 = Array.isArray(config.province_mapping) ? config.province_mapping : [];
    var rcol = (config.region_column ? String(config.region_column) : '').trim();
    var ccol = rcol === 'province' ? 'short' : rcol;
    var officialsByRegion = {};
    PM2.forEach(function (row) {
      if (!row) return;
      var official = row.official != null ? String(row.official).trim() : '';
      if (!official) return;
      var regionVal = (ccol && row[ccol] != null && String(row[ccol]).trim() !== '') ? String(row[ccol]).trim() : (row.short != null ? String(row.short).trim() : '');
      if (!regionVal) return;
      (officialsByRegion[regionVal] = officialsByRegion[regionVal] || []).push(official);
    });
    var regionCentroid = function (region) {
      if (PROVINCE_CENTROID[region]) return PROVINCE_CENTROID[region];
      var offs = officialsByRegion[region];
      if (!offs || !offs.length) return null;
      var lat = 0, lon = 0, n = 0;
      offs.forEach(function (o) { var c = PROVINCE_CENTROID[o]; if (c) { lat += c[0]; lon += c[1]; n++; } });
      return n ? [lat / n, lon / n] : null;
    };
    var mapNodes = [], nodeHas = {};
    Object.keys(regionSet).sort().forEach(function (r) {
      var c = regionCentroid(r);
      if (!c) return;
      nodeHas[r] = true;
      var tot = 0, mix = [];
      Object.keys(genTotalByRegion[r] || {}).forEach(function (cc) { tot += genTotalByRegion[r][cc]; });
      carriers.forEach(function (cc) { var v = E((genTotalByRegion[r] && genTotalByRegion[r][cc]) || 0); if (v > 0) mix.push({ label: cc, value: v }); });
      mapNodes.push({ id: r, label: r, lat: c[0], lon: c[1], value: E(tot), mix: mix });
    });
    var mapEdges = flowRows.filter(function (f) { return nodeHas[f.from] && nodeHas[f.to]; })
      .map(function (f) { var v = f['net_' + unitLabel]; return { from: f.from, to: f.to, value: v, label: f.from + ' → ' + f.to + ': ' + v + ' ' + unitLabel }; });

    // ── Build chart specs ────────────────────────────────────────────────────
    var genMixDonut = {
      kind: 'donut', description: 'Generation by carrier (' + unitLabel + ')',
      slices: carriers.map(function (c) { return { label: c, value: E(carrierEnergy[c]) }; }).filter(function (s) { return s.value > 0; }),
    };
    var capBar = {
      kind: 'bar', description: 'Installed capacity by carrier (GW)', yAxisTitle: 'GW',
      series: [{ key: 'GW', label: 'GW' }],
      rows: capCarriers.map(function (c) { return { label: c, GW: round(cap.capByCarrier[c] / 1000, 3) }; }),
    };
    var capYearRows = capacityByYearRows(cap.fleet, capCarriers);
    var capYearBar = capYearRows ? {
      kind: 'bar', stacked: true, description: 'Installed capacity by carrier by year (GW)', xAxisTitle: 'year', yAxisTitle: 'GW',
      series: capCarriers.map(function (c) { return { key: c }; }), rows: capYearRows,
    } : null;

    var dispatchArea = {
      kind: 'area', stacked: true,
      description: 'Hourly dispatch by carrier (MW), snapshots ' + start + '–' + winEnd,
      xAxisTitle: 'snapshot', yAxisTitle: 'MW',
      series: carriers.map(function (c) { return { key: c }; }),
      rows: (function () { var rows = []; for (var h = start; h < winEnd; h++) { var row = { label: labels[h] }; carriers.forEach(function (c) { row[c] = round(carrierHourly[c][h], 2); }); rows.push(row); } return rows; })(),
    };
    var loadLine = {
      kind: 'line', description: 'System load (MW), snapshots ' + start + '–' + winEnd, xAxisTitle: 'snapshot', yAxisTitle: 'MW',
      series: [{ key: 'load', label: 'load (MW)' }],
      rows: (function () { var rows = []; for (var h = start; h < winEnd; h++) rows.push({ label: labels[h], load: round(loadHourly[h], 2) }); return rows; })(),
    };
    var smpLine = {
      kind: 'line', description: 'System price — SMP (KRW/MWh), snapshots ' + start + '–' + winEnd, xAxisTitle: 'snapshot', yAxisTitle: 'KRW/MWh',
      series: [{ key: 'smp', label: 'SMP' }],
      rows: (function () { var rows = []; for (var h = start; h < winEnd && h < smp.length; h++) rows.push({ label: labels[h], smp: round(smp[h], 1) }); return rows; })(),
    };
    var emisCum = 0;
    var emisArea = {
      kind: 'area', description: 'CO₂ emissions — cumulative (MtCO₂)', xAxisTitle: 'snapshot', yAxisTitle: 'MtCO₂',
      series: [{ key: 'co2', label: 'cumulative MtCO₂' }],
      rows: emisSeries.map(function (e, i) { emisCum += e; return { label: labels[i] || String(i), co2: round(emisCum / 1e6, 4) }; }),
    };
    var ndc = num(config.ndc_target_mt);
    var co2VsNdc = (ndc > 0) ? {
      kind: 'bar', description: 'CO₂ vs NDC target (MtCO₂)', yAxisTitle: 'MtCO₂',
      series: [{ key: 'MtCO2', label: 'MtCO₂' }],
      rows: [{ label: 'this run', MtCO2: totalCO2Mt }, { label: 'NDC target', MtCO2: round(ndc, 3) }],
    } : null;
    var ldcRows = loadHourly.slice().sort(function (a, b) { return b - a; });
    var ldcLine = {
      kind: 'line', description: 'Load-duration curve (MW)', xAxisTitle: 'hours (sorted)', yAxisTitle: 'MW',
      series: [{ key: 'load', label: 'load (MW)' }],
      rows: ldcRows.map(function (v, i) { return { label: String(i), load: round(v, 2) }; }),
    };
    var flowMap = {
      kind: 'map', description: 'Inter-region net flow (' + unitLabel + ') — pie = generation mix, line = net flow',
      nodes: mapNodes, edges: mapEdges,
    };

    // ── Tables ───────────────────────────────────────────────────────────────
    var genTable = carriers.map(function (c) {
      return { carrier: c, ['energy_' + unitLabel]: E(carrierEnergy[c]), share_pct: round(totalGenMWh > 0 ? carrierEnergy[c] / totalGenMWh * 100 : 0, 2) };
    }).sort(function (x, y) { return y['energy_' + unitLabel] - x['energy_' + unitLabel]; });
    var capTable = capCarriers.map(function (c) { return { carrier: c, capacity_GW: round(cap.capByCarrier[c] / 1000, 3) }; })
      .sort(function (x, y) { return y.capacity_GW - x.capacity_GW; });
    var emisByCarrier = (result.emissionsBreakdown && result.emissionsBreakdown.byCarrier) || [];
    var emisTable = emisByCarrier.map(function (e) { return { carrier: e.carrier || e.label, MtCO2: round(num(e.emissions != null ? e.emissions : e.value) / 1e6, 4) }; });
    var adequacyTable = [
      { metric: 'Peak demand (MW)', value: round(peakDemand, 1) },
      { metric: 'Installed capacity (MW)', value: round(cap.totalCapMW, 1) },
      { metric: 'Reserve margin (%)', value: reserveMargin },
    ];

    // ── CSV stash for download ───────────────────────────────────────────────
    var aggSections = [
      { title: 'Generation by carrier (' + unitLabel + ')', rows: genTable },
      { title: 'Installed capacity by carrier (GW)', rows: capTable },
      capYearRows ? { title: 'Capacity by carrier by year (GW)', rows: capYearRows } : null,
      emisTable.length ? { title: 'Emissions by carrier (MtCO₂)', rows: emisTable } : null,
      { title: 'Inter-region net flow (' + unitLabel + ')', rows: flowRows },
      { title: 'Adequacy', rows: adequacyTable },
    ].filter(Boolean);
    var aggParts = [];
    aggSections.forEach(function (s) { if (s.rows && s.rows.length) { aggParts.push('# ' + s.title); aggParts.push(csvFromRows(s.rows)); aggParts.push(''); } });
    if (typeof window !== 'undefined') {
      window.__rsa_export = { filename: 'scenario_analytics_' + unitLabel + '.csv', csv: aggParts.join('\n') };
    }

    // ── Output (KPIs first, then charts, then tables) ────────────────────────
    var out = {};
    out['Total generation (' + unitLabel + ')'] = E(totalGenMWh);
    out['Renewable share (%)'] = rePct;
    out['Total CO₂ (MtCO₂)'] = totalCO2Mt;
    out['Emission factor (gCO₂/kWh)'] = emissionFactor;
    out['Average SMP (KRW/MWh)'] = smpAvg;
    out['Zero-price hours (%)'] = zeroPricePct;
    out['Peak demand (MW)'] = round(peakDemand, 1);
    out['Reserve margin (%)'] = reserveMargin;
    out['Renewable curtailment (%)'] = curtailPct;

    out['Generation mix'] = genMixDonut;
    out['Installed capacity by carrier (GW)'] = capBar;
    if (capYearBar) out['Capacity by carrier by year (GW)'] = capYearBar;
    out['Hourly dispatch by carrier (MW)'] = dispatchArea;
    out['System load over window (MW)'] = loadLine;
    out['System price — SMP'] = smpLine;
    out['CO₂ emissions (cumulative)'] = emisArea;
    if (co2VsNdc) out['CO₂ vs NDC target'] = co2VsNdc;
    out['Inter-region flow map'] = flowMap;
    out['Load-duration curve'] = ldcLine;

    out['Generation by carrier — table'] = genTable;
    out['Installed capacity — table'] = capTable;
    if (emisTable.length) out['Emissions by carrier — table'] = emisTable;
    out['Inter-region flow — table'] = flowRows;
    out['Adequacy — table'] = adequacyTable;

    return out;
  },

  // Download the aggregated tables (stashed on window by analyze) as one CSV.
  downloadAnalytics: function downloadAnalytics(config) {
    var store = (typeof window !== 'undefined') ? window.__rsa_export : null;
    if (!store || !store.csv) {
      return { ok: false, message: 'Nothing to export yet — run the model and open the Output tab first.' };
    }
    try {
      var blob = new Blob([store.csv], { type: 'text/csv;charset=utf-8;' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = store.filename || 'scenario_analytics.csv';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
      return { ok: true, message: 'Downloaded ' + (store.filename || 'scenario_analytics.csv') };
    } catch (e) {
      return { ok: false, message: 'Download failed: ' + (e && e.message ? e.message : String(e)) };
    }
  },
};
