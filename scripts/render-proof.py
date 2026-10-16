#!/usr/bin/env python3
"""Render the completed capacity record as a dependency-free interactive HTML report.

Run from any directory: python3 scripts/render-proof.py
This reads evidence only; it never runs a load test or invents missing measurements.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import subprocess
from urllib.parse import quote, urlsplit


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path, required: bool = False):
    if not path.is_file():
        if required:
            raise SystemExit(f"Required evidence is missing: {path}")
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise SystemExit(f"Cannot read evidence {path}: {error}") from error


def finite(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def numeric_setting(value):
    if value is None:
        return None
    try:
        return finite(float(value))
    except (ValueError, TypeError):
        return None


def branch_name():
    result = subprocess.run(["git", "branch", "--show-current"], cwd=ROOT, capture_output=True, text=True, check=False)
    return result.stdout.strip() or "main"


def load_stage(directory: Path, artifact):
    summary = read_json(directory / "summary.json")
    accounting = read_json(directory / "accounting.json")
    if not summary or not accounting:
        return None  # An in-progress stage is not a completed result.
    machine = read_json(directory / "machine.json") or {}
    settings = machine.get("settings") or {}
    match = re.fullmatch(r"active-(\d+)", directory.name)
    workers = numeric_setting(settings.get("VUS"))
    if workers is None and match:
        workers = int(match[1])  # Directory names are explicit experiment settings.
    if workers is None:
        return None
    metrics = summary.get("metrics") or {}
    per_endpoint = []
    for endpoint in ["feed", "post", "like", "create"]:
        values = metrics.get(f"full_request_ms{{phase:hold,endpoint:{endpoint}}}", {}).get("values", {})
        if values:
            per_endpoint.append({"endpoint": endpoint, "p95": finite(values.get("p(95)")),
                                 "p99": finite(values.get("p(99)"))})
    aggregate = metrics.get("full_request_ms{phase:hold}", {}).get("values", {})
    p95s = [entry["p95"] for entry in per_endpoint if entry["p95"] is not None]
    p99s = [entry["p99"] for entry in per_endpoint if entry["p99"] is not None]
    request_count = metrics.get("http_reqs", {}).get("values", {}).get("count")
    semantic_errors = metrics.get("semantic_success", {}).get("values", {}).get("fails")
    outstanding = accounting.get("client_outstanding_requests_started_in_hold") or {}
    return {"workers": workers, "duration_s": finite(accounting.get("configured_hold_seconds")),
            "passed": accounting.get("passed_all_checks") is True,
            "rps": finite(accounting.get("hold_started_validated_successes_per_configured_second")),
            "p95": max(p95s) if p95s else None, "p99": max(p99s) if p99s else None,
            "aggregate_p95": finite(aggregate.get("p(95)")), "aggregate_p99": finite(aggregate.get("p(99)")),
            "errors": finite(semantic_errors), "requests": finite(request_count),
            "outstanding_peak": finite(outstanding.get("peak")),
            "outstanding_mean": finite(outstanding.get("mean_over_first_start_to_last_event")),
            "accounting_complete": accounting.get("complete_request_accounting") is True,
            "endpoints": per_endpoint, "directory": directory.name,
            "source": artifact(directory), "summary": artifact(directory / "summary.json"),
            "accounting": artifact(directory / "accounting.json")}


def load_intervals(directory: Path, artifact):
    path = directory / "intervals.jsonl"
    if not path.is_file():
        return None
    points = []
    try:
        for line in path.read_text().splitlines():
            if line.strip():
                item = json.loads(line)
                at = finite(item.get("epoch_second"))
                responses = finite(item.get("validated_successes"))
                if at is not None and responses is not None:
                    points.append({"epoch_second": at, "rps": responses})
    except (ValueError, OSError) as error:
        raise SystemExit(f"Cannot parse intervals {path}: {error}") from error
    points.sort(key=lambda p: p["epoch_second"])
    if not points:
        return None
    first, last = int(points[0]["epoch_second"]), int(points[-1]["epoch_second"])
    # No bucket is fabricated: gaps remain gaps, rather than becoming zero throughput.
    for point in points:
        point["elapsed_s"] = point["epoch_second"] - first
    return {"points": points, "first_epoch_second": first, "last_epoch_second": last,
            "source": artifact(path)}


HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#f5f4ee"><title>Small Server — measured capacity</title>
<style>
:root{color-scheme:light;--paper:#f5f4ee;--surface:#fffefa;--ink:#20221f;--muted:#686d65;--line:#dedfd5;--blue:#254ee8;--light:#edf0ff;--green:#24673c;--red:#a53227;--mono:ui-monospace,SFMono-Regular,Consolas,monospace;--sans:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:14px/1.6 var(--sans)}a{color:var(--blue);text-underline-offset:3px}button,select{font:inherit;color:inherit}button{cursor:pointer}button:focus-visible,a:focus-visible,select:focus-visible,[tabindex]:focus-visible{outline:3px solid #91a6ff;outline-offset:4px}[hidden]{display:none!important}.wrap{max-width:1180px;margin:auto;padding:32px 44px 40px}.mast{display:flex;justify-content:space-between;align-items:center;gap:18px;border-bottom:1px solid var(--line);padding-bottom:22px}.brand{font-size:18px;font-weight:750;letter-spacing:-.7px;display:flex;gap:10px;align-items:center}.mark{width:30px;height:32px;background:var(--blue);border-radius:6px;color:#fff;display:grid;place-items:center;font:20px var(--mono)}.mast-note{font:10px var(--mono);color:var(--muted);text-transform:uppercase;letter-spacing:.8px}.intro{margin:40px 0 28px}.eyebrow{font:10px var(--mono);letter-spacing:1.6px;color:var(--blue);text-transform:uppercase;margin:0 0 13px}h1{font-size:clamp(33px,4.5vw,53px);font-weight:550;letter-spacing:-2px;line-height:1.12;margin:0 0 17px}h1 em{font-family:Georgia,serif;font-weight:400}.intro p{font-size:13px;line-height:1.9;max-width:690px;color:var(--muted);margin:0}.machine{border:1px solid var(--line);border-radius:7px;background:var(--surface);padding:13px 17px;font:10px/1.8 var(--mono);margin-bottom:28px;color:var(--muted);overflow-wrap:anywhere}.section-heading{display:flex;justify-content:space-between;align-items:start;gap:20px;margin:30px 0 16px}.section-heading h2{font-size:23px;letter-spacing:-.7px;font-weight:550;margin:0 0 6px}.section-heading p{font-size:12px;color:var(--muted);margin:0;max-width:650px;line-height:1.8}.tag{font:9px var(--mono);letter-spacing:.5px;border:1px solid var(--line);padding:7px 9px;border-radius:4px;white-space:nowrap;background:var(--surface)}.cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.card{border:1px solid var(--line);border-radius:8px;padding:21px;background:var(--surface);min-width:0}.card:first-child{border-top:3px solid var(--blue);padding-top:19px}.card h3{font:10px var(--mono);color:var(--muted);letter-spacing:.5px;text-transform:uppercase;margin:0 0 20px}.big{font-size:37px;line-height:1.12;letter-spacing:-1.7px;font-weight:550}.unit{font-size:11px;color:var(--muted);margin:5px 0 20px}.rows{display:grid;gap:9px}.row{display:flex;justify-content:space-between;gap:16px;font-size:11px}.row span{color:var(--muted)}.row strong{font-weight:550;text-align:right;overflow-wrap:anywhere}.card-note{border-top:1px solid var(--line);padding-top:13px;margin:17px 0 0;font:10px/1.8 var(--mono);color:var(--muted)}.panel{background:var(--surface);border:1px solid var(--line);border-radius:9px;overflow:hidden}.chart-head{display:flex;align-items:center;justify-content:space-between;gap:15px;padding:17px 21px;border-bottom:1px solid var(--line)}.chart-title{font-size:12px;font-weight:600}.controls{display:flex;background:var(--paper);padding:3px;border-radius:5px;gap:2px}.controls button{font-size:10px;padding:6px 10px;border:0;border-radius:3px;background:transparent;white-space:nowrap}.controls button[aria-pressed=true]{background:var(--blue);color:white}.chart-wrap{padding:19px 18px 6px}.chart{display:block;width:100%;height:auto;overflow:visible}.chart text{font:10px var(--mono);fill:var(--muted)}.chart .grid{stroke:var(--line);stroke-width:1}.chart .axis-title{font-size:10px;fill:var(--ink)}.chart .slo{stroke:var(--red);stroke-width:1;stroke-dasharray:5 5}.chart .slo-label{fill:var(--red);font-size:9px}.chart .bar95{fill:var(--blue)}.chart .bar99{fill:#b1bffe}.chart .fail{fill:var(--red)}.chart .fail99{fill:#e9aaa0}.chart .selected-bg{fill:#f0f2fa}.chart .line{stroke:var(--blue);stroke-width:2;fill:none;stroke-linejoin:round;stroke-linecap:round}.chart .area{fill:#edf0ff}.chart .dot{fill:var(--blue);stroke:var(--surface);stroke-width:2}.chart .chosen{stroke:var(--ink);stroke-width:2}.chart [role=button]{cursor:pointer}.chart [role=button]:hover{opacity:.75}.legend{display:flex;gap:17px;padding:0 22px 16px;font:9px var(--mono);color:var(--muted);flex-wrap:wrap}.legend span{display:flex;align-items:center;gap:6px}.swatch{width:8px;height:8px;background:var(--blue);display:inline-block}.swatch.p99{background:#b1bffe}.swatch.failed{background:var(--red)}.chart-caption{padding:13px 21px;border-top:1px solid var(--line);font-size:11px;color:var(--muted);line-height:1.8}.chart-caption a{white-space:nowrap}.stage-picks{padding:16px 21px;border-top:1px solid var(--line);display:flex;gap:7px;flex-wrap:wrap}.stage-picks button{border:1px solid var(--line);border-radius:5px;background:var(--paper);font:10px var(--mono);padding:7px 10px}.stage-picks button[aria-pressed=true]{border-color:var(--blue);background:var(--light);color:var(--blue)}.stage-picks .result{font-size:8px;margin-left:6px}.stage-picks .pass{color:var(--green)}.stage-picks .fail{color:var(--red)}.details{display:grid;grid-template-columns:1.1fr 1fr;gap:23px;padding:21px;border-top:1px solid var(--line);background:#fafbf5}.details h3{font-size:16px;font-weight:550;letter-spacing:-.3px;margin:0 0 12px}.status{display:inline-block;border:1px solid #b8d4bc;background:#eff6eb;color:var(--green);font:9px var(--mono);padding:3px 7px;border-radius:4px;margin-left:8px;vertical-align:middle}.status.fail{border-color:#e3b9b0;background:#fff0eb;color:var(--red)}.details p{font-size:11px;line-height:1.8;color:var(--muted);margin:12px 0 0}.endpoint-table{width:100%;border-collapse:collapse;font:10px var(--mono);margin-top:14px}.endpoint-table th{text-align:left;color:var(--muted);font-weight:400}.endpoint-table td,.endpoint-table th{padding:6px 0;border-bottom:1px solid var(--line)}.endpoint-table td:nth-child(n+2),.endpoint-table th:nth-child(n+2){text-align:right}.notes-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:23px}.note-panel{padding:21px;border:1px solid var(--line);border-radius:8px;background:var(--surface)}.note-panel h3{font-size:13px;margin:0 0 10px;font-weight:600}.note-panel p,.note-panel li{font-size:11px;line-height:1.9;color:var(--muted)}.note-panel p{margin:0}.note-panel ul{margin:0;padding-left:17px;display:grid;gap:5px}.evidence{font:10px/2 var(--mono);color:var(--muted)}.evidence ul{padding:0;list-style:none;margin:12px 0 0;display:flex;gap:6px 18px;flex-wrap:wrap}details.raw{margin-top:23px;font:11px var(--mono)}details.raw summary{cursor:pointer;color:var(--blue)}details.raw pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:350px;overflow:auto;padding:18px;background:var(--surface);border:1px solid var(--line);font:10px/1.8 var(--mono);border-radius:7px}.foot{margin-top:32px;border-top:1px solid var(--line);padding-top:17px;display:flex;justify-content:space-between;gap:20px;font:9px/1.8 var(--mono);color:var(--muted)}.empty{padding:27px;color:var(--muted);font-size:12px}.line-readout{font:10px var(--mono);color:var(--muted);padding:0 21px 17px}.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}
@media(max-width:760px){.wrap{padding:24px}.cards{gap:10px}.card{padding:17px}.card:first-child{padding-top:15px}.big{font-size:31px}.row{font-size:10px}.details{gap:16px}.notes-grid{grid-template-columns:1fr}.chart-head{padding:15px 17px}.chart-wrap{padding:15px 8px 5px}.mast-note{font-size:8px}.section-heading h2{font-size:21px}.tag{font-size:8px}}
@media(max-width:540px){.wrap{padding:22px 18px}.mast{padding-bottom:18px}.brand{font-size:16px}.mast-note{font-size:7px;text-align:right;max-width:120px}.intro{margin:30px 0 23px}.intro p{font-size:12px}h1{letter-spacing:-1.3px}.machine{font-size:9px;padding:11px 13px}.cards{grid-template-columns:1fr}.card{display:grid;grid-template-columns:1fr 1fr;gap:0 16px}.card h3{grid-column:1/-1;margin-bottom:15px}.card .rows{grid-column:2;grid-row:2/4;margin:0}.card .unit{margin-bottom:0}.card-note{grid-column:1/-1;margin-top:15px;padding-top:10px;font-size:9px}.section-heading{gap:10px}.section-heading h2{font-size:20px}.section-heading p{font-size:11px}.tag{padding:6px;font-size:7px}.chart-head{flex-wrap:wrap;gap:12px}.controls{width:100%}.controls button{flex:1}.details{grid-template-columns:1fr;padding:17px}.chart-caption,.legend{padding-left:17px;padding-right:17px}.stage-picks{padding:14px 17px;gap:5px}.stage-picks button{padding:7px 8px;font-size:9px}.stage-picks .result{font-size:7px}.chart-caption{font-size:10px}.legend{font-size:8px}.foot{font-size:8px}.endpoint-table{font-size:9px}.chart text{font-size:11px}.chart .axis-title{font-size:11px}.chart .slo-label{font-size:10px}}
</style></head><body><main class="wrap">
<header class="mast"><div class="brand"><span class="mark" aria-hidden="true">{ }</span>small server<span style="color:var(--blue)">.</span></div><span class="mast-note">RUST API LAB / MEASURED CAPACITY</span></header>
<section class="intro"><p class="eyebrow">A SMALL API. AN OPEN BOOK.</p><h1>How much work?<br><em>Here is the evidence.</em></h1><p>A Rust + io_uring + SQLite API, tested on this machine. Explore the request-worker ladder, inspect the sustained holds, and keep browsing users separate from requests in flight.</p></section>
<div class="machine" id="machine"></div>
<div class="section-heading"><div><h2>Sustained measurements.</h2><p>Three different workloads. Each value comes from the completed measurement record; durations and error counts stay attached.</p></div><span class="tag">ACTUAL LOCAL RUNS</span></div>
<section class="cards" id="cards" aria-label="Sustained measurements"></section>
<section aria-labelledby="ladder-heading"><div class="section-heading"><div><h2 id="ladder-heading">Find the useful range.</h2><p>Short exploration stages locate a candidate. The sustained active hold above is a separate run, not an extrapolation from this ladder.</p></div><span class="tag" id="ladder-duration">EXPLORATION STAGES</span></div>
<div class="panel"><div class="chart-head"><span class="chart-title">Active request workers · exploration</span><div class="controls" role="group" aria-label="Chart measurement"><button id="show-latency" type="button" aria-pressed="true">p95 / p99 latency</button><button id="show-throughput" type="button" aria-pressed="false">Throughput</button></div></div>
<div class="chart-wrap"><svg class="chart" id="ladder-chart" viewBox="0 0 920 345" role="img" aria-labelledby="chart-title chart-description"><title id="chart-title">Active worker ladder</title><desc id="chart-description">Select a worker stage below for exact measurements and evidence links.</desc></svg></div>
<div class="legend" id="ladder-legend"></div><div class="stage-picks" id="stage-picks" role="group" aria-label="Select an exploration stage"></div><div class="details" id="stage-detail" aria-live="polite"></div>
<div class="chart-caption">Latency bars show the worst endpoint p95 and worst endpoint p99, which may belong to different endpoints. The p95 limit is 500 ms; the p99 limit is 1,000 ms. Throughput counts validated requests started in the hold, divided by its configured duration, including any completion drain. Select a stage for exact values.</div></div></section>
<section id="timeline-section" hidden><div class="section-heading"><div><h2>The sustained hold, second by second.</h2><p>Validated response completions in observed UTC second buckets. Edge buckets may be partial; the timeline includes any completion drain.</p></div><span class="tag" id="timeline-duration">ACTIVE HOLD</span></div><div class="panel"><div class="chart-head"><span class="chart-title">Validated completions / observed second</span><span class="mast-note">HOVER OR FOCUS A POINT</span></div><div class="chart-wrap"><svg id="timeline" class="chart" viewBox="0 0 920 260" role="img" aria-label="Per-second validated response completion counts during the active hold"></svg></div><p class="line-readout" id="timeline-readout" aria-live="polite">Each plotted point is an observed completion bucket.</p><div class="chart-caption">This chart uses completion-time buckets, while the headline throughput uses hold-started requests per configured second. They have different boundaries. Missing buckets are left as gaps. <a id="timeline-source">Inspect interval data ↗</a></div></div></section>
<div class="notes-grid"><section class="note-panel"><h3>What these numbers prove.</h3><p>A passing sustained run establishes a tested load for this machine, source, workload, and duration. Worker counts bound client outstanding work, including connection waits. Browsing VUs spend time thinking; an arrival-rate test schedules requests independently. None is a count of simultaneous SQLite execution: the engine serializes database work.</p></section><section class="note-panel"><h3>Read the limits with the result.</h3><ul id="notes"><li>The load generator and server share this machine. Client CPU, memory, sockets, and measurement output can constrain observed capacity.</li><li>Loopback measurements exclude phone Wi-Fi, Internet latency, TLS, and public-tunnel overhead.</li><li>The largest tested pass is a lower bound under its workload. A failed stage does not isolate the server's absolute ceiling.</li></ul></section></div>
<section class="note-panel evidence" style="margin-top:20px"><h3>Follow every result back to a file.</h3><div>Exact k6 summaries, request accounting, per-second events, and resource samples accompany each run.</div><ul id="evidence-links"></ul></section>
<details class="raw"><summary>Inspect the published measurement record</summary><pre id="raw-record" tabindex="0"></pre></details>
<footer class="foot"><span>RUST / io_uring / SQLITE<br>NO INVENTED CAPACITY. NO CROSS-MACHINE SPEEDUP CLAIM.</span><span id="footer-meta"></span></footer>
</main><script type="application/json" id="report-data">__REPORT_DATA__</script><script>
(()=>{'use strict';const D=JSON.parse(document.getElementById('report-data').textContent);const $=id=>document.getElementById(id);const NS='http://www.w3.org/2000/svg';let mode='latency';let selected=Math.max(0,D.stages.map((s,i)=>s.passed?i:-1).filter(i=>i>=0).pop()??0);
function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=String(text);return n}function num(x,d=0){return typeof x==='number'&&Number.isFinite(x)?x.toLocaleString(undefined,{maximumFractionDigits:d}):'—'}function val(x,unit='',d=1){return typeof x==='number'&&Number.isFinite(x)?num(x,d)+(unit?' '+unit:''):'—'}function row(label,value){const n=el('div','row');n.append(el('span','',label),el('strong','',value));return n}function link(text,href){const a=el('a','',text);a.href=href;return a}function svg(tag,attrs={},text){const n=document.createElementNS(NS,tag);Object.entries(attrs).forEach(([key,value])=>n.setAttribute(key,value));if(text!==undefined)n.textContent=String(text);return n}function appendSVG(root,tag,attrs,text){const n=svg(tag,attrs,text);root.append(n);return n}function extent(values,floor=0){return Math.max(floor,...values.filter(x=>typeof x==='number'&&Number.isFinite(x)))}
const m=D.proof.machine||{};const machine=[];if(m.cpu)machine.push(String(m.cpu));if(typeof m.memory_gib==='number')machine.push(num(m.memory_gib,1)+' GiB RAM');machine.push('Co-located generator + server / Linux loopback');$('machine').textContent=machine.join(' / ');$('raw-record').textContent=JSON.stringify(D.proof,null,2);$('footer-meta').append(el('span','','Generated '+D.generated_utc));if(D.repo){$('footer-meta').append(document.createElement('br'),link('Project source + complete evidence ↗',D.repo));}
const definitions=[{key:'active',title:'Active request workers',field:'concurrency',unit:'workers · zero think time',extra:[['Observed outstanding peak',D.active_outstanding?.peak],['Observed outstanding mean',D.active_outstanding?.mean_over_first_start_to_last_event]]},{key:'users',title:'Browsing virtual users',field:'vus',unit:'browsing VUs · includes think time'},{key:'open',title:'Open arrival rate',field:'rate',unit:'target HTTP requests per second'}];
definitions.forEach(def=>{const item=D.proof[def.key];const card=el('article','card');card.append(el('h3','',def.title),el('div','big',num(item?.[def.field])),el('div','unit',def.unit));const rows=el('div','rows');if(item){rows.append(row(def.key==='open'?'Achieved throughput':'Hold throughput',val(item.rps,'req/s',1)),row('p95 / p99',val(item.p95_ms,'ms')+' / '+val(item.p99_ms,'ms')),row('Measured duration',val(item.duration_s,'s',0)),row('Errors',num(item.errors)));if(def.key==='open')rows.append(row('Dropped arrivals',num(item.dropped)));}else rows.append(row('Measurement','Not in published record'));card.append(rows);const note=el('div','card-note');if(def.extra&&def.extra.some(x=>typeof x[1]==='number'))def.extra.forEach(([label,value])=>{if(typeof value==='number')note.append(el('div','',label+': '+num(value,1)));});const passed=D.hold_status[def.key];if(typeof passed==='boolean')note.append(el('div','',passed?'Recorded acceptance checks passed.':'Recorded acceptance checks failed.'));else note.append(el('div','','See the source record for acceptance details.'));card.append(note);$('cards').append(card);});
const durations=[...new Set(D.stages.map(s=>s.duration_s).filter(x=>x!==null))];if(durations.length===1)$('ladder-duration').textContent=num(durations[0])+'-SECOND EXPLORATION';
function renderDetail(){const s=D.stages[selected];const box=$('stage-detail');box.replaceChildren();if(!s){box.append(el('p','','No completed exploration stage is available.'));return}const left=el('div');const heading=el('h3','',num(s.workers)+' active workers');heading.append(el('span','status'+(s.passed?'':' fail'),s.passed?'PASS':'FAIL'));left.append(heading);const rows=el('div','rows');rows.append(row('Configured measured hold',val(s.duration_s,'s',0)),row('Validated hold-started throughput',val(s.rps,'req/s',1)),row('Semantic errors',num(s.errors)),row('HTTP requests · all phases',num(s.requests)),row('Accounting balanced',s.accounting_complete?'Yes':'No'));left.append(rows);const sources=el('p');sources.append(link('Run artifacts ↗',s.source),document.createTextNode(' · '),link('k6 summary',s.summary),document.createTextNode(' · '),link('Request accounting',s.accounting));left.append(sources);const right=el('div');right.append(row('Observed client outstanding peak',num(s.outstanding_peak)),row('Time-weighted outstanding mean',num(s.outstanding_mean,1)));const table=el('table','endpoint-table');const caption=el('caption','sr-only','Full request latency by endpoint during hold');table.append(caption);const thead=el('thead'),tr=el('tr');['Endpoint','p95 ms','p99 ms'].forEach(text=>{const th=el('th','',text);th.scope='col';tr.append(th)});thead.append(tr);table.append(thead);const tbody=el('tbody');s.endpoints.forEach(ep=>{const r=el('tr');r.append(el('td','',ep.endpoint),el('td','',num(ep.p95,2)),el('td','',num(ep.p99,2)));tbody.append(r)});table.append(tbody);right.append(table);right.append(el('p','','Full duration includes client connection/pool waits, response-body consumption, and semantic validation.'));box.append(left,right);}
function choose(index){selected=index;renderLadder();renderDetail()}
function renderLadder(){const chart=$('ladder-chart');chart.replaceChildren(svg('title',{id:'chart-title'},mode==='latency'?'Worst endpoint latency across worker stages':'Validated throughput across worker stages'),svg('desc',{id:'chart-description'},'Select a stage below for its exact measurements.'));const stages=D.stages;if(!stages.length){appendSVG(chart,'text',{x:45,y:120},'No completed ladder measurements.');return}const W=920,H=345,L=67,R=32,T=30,B=65,pw=W-L-R,ph=H-T-B;const max=mode==='latency'?extent(stages.flatMap(s=>[s.p95,s.p99]),1000)*1.15:extent(stages.map(s=>s.rps))*1.18;const y=v=>T+ph-(max?v/max:0)*ph;for(let i=0;i<=4;i++){const value=max*i/4;appendSVG(chart,'line',{x1:L,x2:W-R,y1:y(value),y2:y(value),class:'grid'});appendSVG(chart,'text',{x:L-12,y:y(value)+4,'text-anchor':'end'},num(value,0))}appendSVG(chart,'text',{x:L,y:15,class:'axis-title'},mode==='latency'?'Full request latency · ms':'Validated requests / configured hold second');const step=pw/stages.length;stages.forEach((s,i)=>{const x=L+step*(i+.5);if(i===selected)appendSVG(chart,'rect',{x:L+step*i+3,y:T,width:step-6,height:ph,rx:5,class:'selected-bg'});const g=appendSVG(chart,'g',{'role':'button',tabindex:0,'aria-label':num(s.workers)+' workers, '+(s.passed?'passed':'failed')+', select details'});g.addEventListener('click',()=>choose(i));g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose(i)}});if(mode==='latency'){const bw=Math.min(28,step*.22);[['p95',x-bw-2,s.passed?'bar95':'fail'],['p99',x+2,s.passed?'bar99':'fail99']].forEach(([key,bx,cls])=>{if(s[key]!==null){const bar=appendSVG(g,'rect',{x:bx,y:y(s[key]),width:bw,height:Math.max(1,T+ph-y(s[key])),rx:2,class:cls});bar.append(svg('title',{},num(s.workers)+' workers · '+key+' '+num(s[key],2)+' ms'));}})}else if(s.rps!==null){const bar=appendSVG(g,'rect',{x:x-Math.min(28,step*.25),y:y(s.rps),width:Math.min(56,step*.5),height:Math.max(1,T+ph-y(s.rps)),rx:3,class:s.passed?'bar95':'fail'});bar.append(svg('title',{},num(s.workers)+' workers · '+num(s.rps,2)+' validated req/s'));}appendSVG(chart,'text',{x,y:H-B+22,'text-anchor':'middle'},num(s.workers));});if(mode==='latency'){[[500,'p95 limit · 500 ms'],[1000,'p99 limit · 1,000 ms']].forEach(([value,label])=>{appendSVG(chart,'line',{x1:L,x2:W-R,y1:y(value),y2:y(value),class:'slo'});appendSVG(chart,'text',{x:W-R,y:y(value)-7,'text-anchor':'end',class:'slo-label'},label)});}appendSVG(chart,'text',{x:L+pw/2,y:H-9,'text-anchor':'middle',class:'axis-title'},'Configured active request workers');const legend=$('ladder-legend');legend.replaceChildren();(mode==='latency'?[['','Worst endpoint p95'],['p99','Worst endpoint p99'],['failed','Failed acceptance']]:[['','Passed acceptance'],['failed','Failed acceptance']]).forEach(([cls,text])=>{const item=el('span');item.append(el('i','swatch '+cls),document.createTextNode(text));legend.append(item)});const picks=$('stage-picks');picks.replaceChildren();stages.forEach((s,i)=>{const b=el('button','',num(s.workers));b.type='button';b.setAttribute('aria-pressed',String(i===selected));b.setAttribute('aria-label',num(s.workers)+' workers, '+(s.passed?'passed':'failed'));b.append(el('span','result '+(s.passed?'pass':'fail'),s.passed?'PASS':'FAIL'));b.addEventListener('click',()=>choose(i));picks.append(b)});}
$('show-latency').addEventListener('click',()=>{mode='latency';$('show-latency').setAttribute('aria-pressed','true');$('show-throughput').setAttribute('aria-pressed','false');renderLadder()});$('show-throughput').addEventListener('click',()=>{mode='throughput';$('show-latency').setAttribute('aria-pressed','false');$('show-throughput').setAttribute('aria-pressed','true');renderLadder()});renderLadder();renderDetail();
if(D.timeline?.points.length){$('timeline-section').hidden=false;$('timeline-source').href=D.timeline.source;if(typeof D.proof.active?.duration_s==='number')$('timeline-duration').textContent=num(D.proof.active.duration_s)+'-SECOND ACTIVE HOLD';const root=$('timeline');const points=D.timeline.points;const W=920,H=260,L=67,R=30,T=22,B=43,pw=W-L-R,ph=H-T-B;const xmax=extent(points.map(p=>p.elapsed_s),1),ymax=extent(points.map(p=>p.rps),1)*1.12;const x=t=>L+t/xmax*pw,y=v=>T+ph-v/ymax*ph;for(let i=0;i<=4;i++){const v=ymax*i/4;appendSVG(root,'line',{x1:L,x2:W-R,y1:y(v),y2:y(v),class:'grid'});appendSVG(root,'text',{x:L-12,y:y(v)+4,'text-anchor':'end'},num(v));}let segment=[];const segments=[];points.forEach((p,i)=>{if(i&&p.elapsed_s-points[i-1].elapsed_s>1){segments.push(segment);segment=[]}segment.push(p)});if(segment.length)segments.push(segment);segments.forEach(seg=>{const coords=seg.map(p=>x(p.elapsed_s)+','+y(p.rps)).join(' ');appendSVG(root,'polygon',{points:x(seg[0].elapsed_s)+','+(T+ph)+' '+coords+' '+x(seg[seg.length-1].elapsed_s)+','+(T+ph),class:'area'});appendSVG(root,'polyline',{points:coords,class:'line'});});for(let i=0;i<=4;i++){const t=xmax*i/4;appendSVG(root,'text',{x:x(t),y:H-20,'text-anchor':'middle'},num(t)+' s')}points.forEach(p=>{const dot=appendSVG(root,'circle',{cx:x(p.elapsed_s),cy:y(p.rps),r:3.3,class:'dot',tabindex:0,'aria-label':num(p.elapsed_s)+' seconds from first bucket, '+num(p.rps)+' validated completions'});const announce=()=>{$('timeline-readout').textContent='Bucket +'+num(p.elapsed_s)+' s · '+num(p.rps)+' validated completions · '+new Date(p.epoch_second*1000).toISOString();};dot.addEventListener('pointerenter',announce);dot.addEventListener('focus',announce);dot.append(svg('title',{},'+'+num(p.elapsed_s)+' s: '+num(p.rps)+' validated completions'));});}
if(Array.isArray(D.proof.notes))D.proof.notes.forEach(note=>$('notes').append(el('li','',typeof note==='string'?note:JSON.stringify(note))));Object.entries(D.artifacts).forEach(([name,url])=>{const li=el('li');li.append(link(name+' ↗',url));$('evidence-links').append(li)});
})();
</script></body></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof", type=Path, default=ROOT / "docs/proof/demo.json")
    parser.add_argument("--runs", type=Path, default=ROOT / "proof/runs")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/proof/report.html")
    parser.add_argument("--branch", default=branch_name(), help="GitHub evidence-link branch")
    args = parser.parse_args()
    proof = read_json(args.proof, required=True)
    if not isinstance(proof, dict) or proof.get("status") != "complete":
        raise SystemExit("Refusing to render uncompleted proof: demo.json must have status=complete.")
    repo = proof.get("repo_url")
    parsed = urlsplit(repo) if isinstance(repo, str) else None
    if not parsed or parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.username or parsed.password:
        repo = None
    else:
        repo = repo.rstrip("/")

    def artifact(path: Path):
        try:
            relative = path.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            relative = path.name
        if repo:
            action = "tree" if path.is_dir() else "blob"
            return f"{repo}/{action}/{quote(args.branch, safe='')}/{quote(relative, safe='/')}"
        # Relative links also work when opening the generated report locally.
        import os
        return quote(os.path.relpath(path.resolve(), args.output.resolve().parent), safe="/.")

    stages = []
    for group in ["ladder", "extended-ladder"]:
        for directory in sorted((args.runs / group).glob("active-*")):
            if directory.is_dir():
                stage = load_stage(directory, artifact)
                if stage is not None:
                    stages.append(stage)
    stages.sort(key=lambda stage: (stage["workers"], stage["source"]))
    hold_dirs = {"active": args.runs / "active-hold", "users": args.runs / "original-hold",
                 "open": args.runs / "open-confirmation"}
    hold_records = {name: read_json(path / "accounting.json") for name, path in hold_dirs.items()}
    artifacts = {"Published measurement record": artifact(args.proof),
                 "All run artifacts": artifact(args.runs),
                 "Benchmark methodology": artifact(ROOT / "bench/README.md"),
                 "Functional proof": artifact(ROOT / "docs/proof/functional-final.json")}
    for name, directory in hold_dirs.items():
        if directory.is_dir():
            artifacts[{"active": "Active hold", "users": "Browsing hold", "open": "Arrival test"}[name]] = artifact(directory)
    active = hold_records["active"] or {}
    data = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "proof": proof, "repo": repo, "stages": stages,
            "hold_status": {name: value.get("passed_all_checks") if value else None
                            for name, value in hold_records.items()},
            "active_outstanding": active.get("client_outstanding_requests_started_in_hold"),
            "timeline": load_intervals(hold_dirs["active"], artifact), "artifacts": artifacts}
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    # Keep arbitrary source strings inside the data element, including </script>.
    encoded = encoded.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    output = HTML.replace("__REPORT_DATA__", encoded)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output)
    print(f"Rendered {args.output}: {len(stages)} completed exploration stages, {len(output.encode()):,} bytes.")


if __name__ == "__main__":
    main()
