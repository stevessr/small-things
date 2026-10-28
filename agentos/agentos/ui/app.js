"use strict";
const $ = id => document.getElementById(id);
const ns = "http://www.w3.org/2000/svg";
let state = null;
let active = null;
let filter = "all";
let search = "";
let inFlight = false;
let dirty = false;
const labels = {
  pending: "等待中", running: "运行中", succeeded: "已完成",
  failed: "失败", blocked: "已阻断"
};
const titles = {
  admitted: "任务纳管", declared: "动态声明", started: "开始执行",
  finished: "执行结束", blocked: "依赖阻断", retry: "重新尝试",
  declaration_rejected: "声明被拒绝"
};
function text(tag, value, className = "") {
  const el = document.createElement(tag);
  el.textContent = String(value ?? "—");
  if (className) el.className = className;
  return el;
}
function svg(tag, attrs = {}, content) {
  const e = document.createElementNS(ns, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  if (content !== undefined) e.textContent = String(content);
  return e;
}
function safeStatus(value) {
  return Object.hasOwn(labels, value) ? value : "pending";
}
function statusPill(value) {
  const s = safeStatus(value);
  return text("span", labels[s], "status-pill " + s);
}
function duration(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value < 1 ? Math.round(value * 1000) + " ms" : value.toFixed(2) + " s";
}
function time(nsValue) {
  if (typeof nsValue !== "number" || !Number.isFinite(nsValue)) return "—";
  return new Date(nsValue / 1e6).toLocaleTimeString("zh-CN", {hour12:false});
}
function nodeData(id) {
  return {spec:state?.dag?.[id] || {}, task:state?.tasks?.[id] || {id, status:"pending"}};
}
function updateMetrics(data) {
  $("metric-total").textContent = data.total ?? "0";
  const count = data.counts || {};
  for (const key of ["succeeded", "running", "pending"]) $("metric-" + key).textContent = count[key] || 0;
  $("metric-failed").textContent = (count.failed || 0) + (count.blocked || 0);
  $("isolation").textContent = data.isolation || "trace-only";
  const b = data.budget || {};
  $("budget").textContent = b.cpu_units ? "CPU " + b.cpu_units + " · RAM " + b.memory_mib + " MiB · max " + b.max_tasks : "资源计划由运行时提供";
  $("updated").textContent = new Date().toLocaleTimeString("zh-CN", {hour12:false});
}
function graphLayout(keys, dag) {
  const idset = new Set(keys);
  const indegrees = new Map(keys.map(k => [k, 0]));
  const children = new Map(keys.map(k => [k, []]));
  const depth = new Map(keys.map(k => [k, 0]));
  for (const id of keys) {
    for (const dep of dag[id]?.deps || []) {
      if (!idset.has(dep)) continue;
      indegrees.set(id, indegrees.get(id) + 1);
      children.get(dep).push(id);
    }
  }
  const ready = keys.filter(k => indegrees.get(k) === 0);
  let count = 0;
  while (ready.length) {
    const key = ready.shift();
    count++;
    for (const child of children.get(key)) {
      depth.set(child, Math.max(depth.get(child), depth.get(key) + 1));
      indegrees.set(child, indegrees.get(child) - 1);
      if (indegrees.get(child) === 0) ready.push(child);
    }
  }
  // DAG validation is owned by the supervisor. Still handle an incomplete
  // live trace or corrupt imported report without infinite layout loops.
  if (count < keys.length) {
    for (const key of keys) if (indegrees.get(key) > 0) depth.set(key, 0);
  }
  const cols = new Map();
  for (const id of keys) {
    const d = depth.get(id);
    if (!cols.has(d)) cols.set(d, []);
    cols.get(d).push(id);
  }
  const out = new Map();
  const maxRows = Math.max(1, ...Array.from(cols.values(), c => c.length));
  const height = Math.max(340, maxRows * 90 + 64);
  const width = Math.max(570, (Math.max(...depth.values(), 0) + 1) * 198 + 100);
  for (const [d, items] of cols) {
    items.sort();
    const startY = (height - items.length * 90) / 2 + 22;
    items.forEach((id, i) => out.set(id, {x: 44 + d * 198, y: startY + i * 90}));
  }
  return {points:out, width, height};
}
function renderGraph() {
  const container = $("dag-svg");
  const empty = $("graph-empty");
  container.replaceChildren();
  const keys = Object.keys(state?.tasks || {});
  const limit = 160;
  const shown = keys.slice(0, limit);
  empty.hidden = !!shown.length;
  if (!shown.length) {
    empty.textContent = "尚无任务数据 · 使用 --trace 运行任务时可实时显示";
    $("graph-caption").textContent = "等待 Agent Runtime 事件";
    return;
  }
  const {points, width, height} = graphLayout(shown, state.dag || {});
  container.setAttribute("viewBox", "0 0 " + width + " " + height);
  container.style.width = width + "px";
  container.style.height = height + "px";
  const defs = svg("defs");
  const marker = svg("marker", {id:"arrow",markerWidth:"8",markerHeight:"8",refX:"7",refY:"3",orient:"auto"});
  marker.append(svg("path", {d:"M0 0 L7 3 L0 6",fill:"none",stroke:"#587399","stroke-width":"1.2"}));
  defs.append(marker);
  container.append(defs);
  for (const id of shown) {
    const p = points.get(id);
    if (!p) continue;
    for (const dep of state.dag?.[id]?.deps || []) {
      const q = points.get(dep);
      if (!q) continue;
      const fromX = q.x + 150, fromY = q.y + 24, toX = p.x, toY = p.y + 24;
      const mid = (fromX + toX) / 2;
      container.append(svg("path", {
        d:"M" + fromX + " " + fromY + " C" + mid + " " + fromY + ", " + mid + " " + toY + ", " + (toX - 7) + " " + toY,
        stroke:"#587399", "stroke-width":"1.4",fill:"none","marker-end":"url(#arrow)"
      }));
    }
  }
  for (const id of shown) {
    const p = points.get(id);
    const {task,spec} = nodeData(id);
    const s = safeStatus(task.status);
    const colors = {
      pending:["#222e42","#526888"], running:["#433825","#bb8c47"],
      succeeded:["#173d34","#319d78"], failed:["#4d2837","#c7657e"],
      blocked:["#392d3a","#8f647d"]
    };
    const [fill,stroke] = colors[s];
    const group = svg("g", {tabindex:"0",role:"button","aria-label":id + " " + labels[s]});
    group.style.cursor = "pointer";
    group.append(svg("rect", {x:p.x,y:p.y,width:150,height:50,rx:8,fill,
      stroke:active===id?"#b6c9fa":stroke,"stroke-width":active===id?2.5:1.2}));
    group.append(svg("circle", {cx:p.x+15,cy:p.y+17,r:4,fill:stroke}));
    group.append(svg("text", {x:p.x+26,y:p.y+21,fill:"#f0f4ff","font-size":"11","font-weight":"650"},id.length>18?id.slice(0,17)+"…":id));
    group.append(svg("text", {x:p.x+15,y:p.y+38,fill:"#a2b5d1","font-size":"9"},(spec.kind||"agent")+" · "+labels[s]));
    group.addEventListener("click",()=>selectTask(id));
    group.addEventListener("keydown", e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();selectTask(id);}});
    container.append(group);
  }
  $("graph-caption").textContent = shown.length + " Agent · " + (keys.length-shown.length?"+ "+(keys.length-shown.length)+" more":"依赖拓扑");
}
function detailKV(name,value) {
  const el = text("div","","detail-keyvalue");
  el.append(text("span",name),text("strong",value));
  return el;
}
function section(title, content) {
  const wrapper = text("div","","detail-section");
  wrapper.append(text("div",title,"detail-label"),content);
  return wrapper;
}
function renderDetails() {
  const el = $("details");el.replaceChildren();
  if (!active || !state?.tasks?.[active]) {
    el.append(text("div","选择左侧任务节点以查看详情","empty"));
    return;
  }
  const {task,spec} = nodeData(active);
  const heading = text("div","","detail-title");
  heading.append(text("b",active),statusPill(task.status));
  el.append(heading,text("p",(spec.kind||"Agent")+" · "+(spec.tenant||"default"),"details-subtitle"));
  const pair = text("div","","detail-pairs");
  pair.append(detailKV("耗时",duration(task.elapsed_s)),detailKV("执行次数",task.attempts??"—"),
              detailKV("CPU 预算",spec.cpu_units??"—"),detailKV("内存预算",(spec.memory_mib??"—")+" MiB"));
  el.append(section("EXECUTION",pair));
  const chips = text("div","","tagline");
  const deps = Array.isArray(spec.deps)?spec.deps:[];
  if (!deps.length) chips.append(text("span","无依赖","chip"));
  for (const dep of deps) chips.append(text("span",dep,"chip"));
  el.append(section("DEPENDENCIES",chips));
  if (state.declared_by?.[active]) el.append(section("DECLARED BY",text("div",state.declared_by[active],"chip")));
  const metrics = task.resource_metrics || {};
  const branch = task.filesystem_branch || metrics.layerfs_branch;
  const commit = task.filesystem_commit || metrics.layerfs_commit;
  if (branch || commit) {
    const labels = text("div","","detail-pairs");
    labels.append(detailKV("LayerFS Branch",branch||"—"),detailKV("FC Checkpoint",commit||"—"));
    el.append(section("LAYERFS / CHECKPOINTS",labels));
  }
  if (Object.keys(metrics).length) el.append(section("RESOURCE METRICS",text("pre",JSON.stringify(metrics,null,2),"code-view")));
  if (task.error) el.append(section("ERROR",text("pre",task.error,"code-view")));
  if (task.stdout) el.append(section("STDOUT",text("pre",task.stdout,"code-view")));
  if (task.stderr) el.append(section("STDERR",text("pre",task.stderr,"code-view")));
}
function renderTable() {
  const target = $("task-rows");target.replaceChildren();
  let count = 0;
  for (const [id,task] of Object.entries(state?.tasks || {}).sort((a,b)=>a[0].localeCompare(b[0]))) {
    const spec = state.dag[id] || {};
    const status = safeStatus(task.status);
    if (filter!=="all"&&status!==filter) continue;
    if (search&&!([id,spec.tenant||"",spec.kind||""] .join(" ").toLowerCase().includes(search))) continue;
    const row = document.createElement("tr");
    if (id===active) row.className="selected";
    const name=text("td",id);
    name.append(text("div",(spec.kind||"process")+" / "+(spec.tenant||"default"),"task-secondary"));
    const cell=document.createElement("td");cell.append(statusPill(status));
    const deps=Array.isArray(spec.deps)?spec.deps:[];
    row.append(name,cell,text("td",deps.length?deps.slice(0,3).join(", ")+(deps.length>3?"…":""):"—"),text("td",duration(task.elapsed_s)));
    row.addEventListener("click",()=>selectTask(id));
    target.append(row);count++;
  }
  if (!count) {
    const row = document.createElement("tr");
    const cell=text("td","没有匹配的任务");cell.colSpan=4;row.append(cell);target.append(row);
  }
}
function renderEvents() {
  const list=$("timeline");list.replaceChildren();
  const events=(state?.events||[]).slice(-80).reverse();
  $("event-count").textContent=(state?.events?.length||0)+" EVENTS";
  if(!events.length){list.append(text("div","尚无运行事件","empty"));return;}
  for(const e of events){
    const item=text("div","","timeline-event");
    const symbol=text("span","","dot "+(e.event||""));
    const body=document.createElement("div");
    body.append(text("strong",(titles[e.event]||e.event)+" · "+(e.task||"—")));
    const description=[e.parent?"by "+e.parent:"",e.error||"",e.status||"",
      e.deps?.length?"deps: "+e.deps.join(", "):""].filter(Boolean).join(" · ");
    if(description)body.append(text("p",description));
    item.append(symbol,body,text("time",time(e.time_ns)));
    list.append(item);
  }
}
function selectTask(id){active=id;renderGraph();renderDetails();renderTable();}
function render(){if(!state)return;updateMetrics(state);renderGraph();renderDetails();renderTable();renderEvents();}
async function poll(){
  // Coalesce bursts of inotify events without dropping the latest state.
  if(inFlight){dirty=true;return;}
  inFlight=true;
  try {
    const response=await fetch("/api/state",{cache:"no-store",headers:{"Accept":"application/json"}});
    if(!response.ok)throw Error("HTTP "+response.status);
    const data=await response.json();
    if(data.error)throw Error(data.error);
    state=data;
    const connection=$("connection");connection.classList.remove("offline");connection.lastChild.textContent="已连接";
    render();
  }catch(error){
    const connection=$("connection");connection.classList.add("offline");connection.lastChild.textContent="连接失败";
    $("updated").textContent=String(error.message||error);
  }finally{
    inFlight=false;
    if(dirty){dirty=false;queueMicrotask(poll);}
  }
}
$("search").addEventListener("input",e=>{search=e.target.value.toLowerCase().trim();renderTable();});
$("filter").addEventListener("change",e=>{filter=e.target.value;renderTable();});
$("refresh").addEventListener("click",poll);
document.querySelectorAll(".nav-link").forEach(link=>link.addEventListener("click",()=>{
  document.querySelectorAll(".nav-link").forEach(n=>n.classList.remove("active"));
  link.classList.add("active");
}));
// EventSource is a push subscription; refresh happens only when files change.
if (typeof EventSource !== "undefined") {
  const stream = new EventSource("/api/changes");
  stream.addEventListener("message", () => poll());
  stream.addEventListener("error", () => {
    const connection = $("connection");
    connection.classList.add("offline");
    connection.lastChild.textContent = "变更通知断开，可手动刷新";
  });
} else {
  poll(); // Non-SSE browsers retain a manual refresh button.
}
