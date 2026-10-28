/**
 * Strict, single-attempt LayerFS 1.1.0 bridge.
 * Public @layerfs/agent methods only; no internal Store schema access.
 * One JSON request on stdin, one JSON result on stdout.
 */
import { pathToFileURL } from "node:url";
import { randomBytes } from "node:crypto";

const MAX_REQUEST = 128 * 1024;
const MAX_OUTPUT = 512 * 1024;
const validName = /^[A-Za-z][A-Za-z0-9_.-]{0,63}$/;

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function safePath(path) {
  assert(typeof path === "string" && path.startsWith("/") && path !== "/" &&
    path.length <= 2048 && !path.includes("\0") &&
    !path.split("/").some(p => p === ".." || p === "."), "invalid absolute file path");
  return path;
}

function safeBranch(id) {
  assert(typeof id === "string" && validName.test(id), "invalid agent ID");
  return "ag-" + id.toLowerCase().slice(0, 40) + "-" + randomBytes(6).toString("hex");
}

function shellEscape(value) {
  assert(typeof value === "string" && value.length < 8192 && !value.includes("\0"), "invalid argument");
  return "'" + value.replaceAll("'", "'\\''") + "'";
}

async function getText(fs, ref, path) {
  // LayerFS 1.1.0 fs.read is bounded to 48 KiB and 2000 lines per call.
  let line = 1, text = "";
  for (let i = 0; i < 256; i++) {
    const page = await fs.read(ref, path, line);
    assert(!page.lineTruncated, "FC refuses truncated long line: " + path);
    assert(typeof page.text === "string", "invalid LayerFS read page");
    text += page.text;
    assert(Buffer.byteLength(text) <= 4 * 1024 * 1024, "FC file exceeds 4 MiB limit");
    if (page.nextLine === null || page.nextLine === undefined) {
      assert(!page.truncated, "FC refuses incomplete file read");
      return text;
    }
    assert(Number.isSafeInteger(page.nextLine) && page.nextLine > line, "invalid read pagination");
    line = page.nextLine;
  }
  throw new Error("FC file exceeds read page limit");
}

async function statOrNull(fs, ref, path) {
  try {
    return await fs.stat(ref, path);
  } catch (error) {
    if (error?.code === "NoSuchPath") return null;
    throw error;
  }
}

async function fcRestore(lf, p) {
  assert(validName.test(p.branch) && typeof p.checkpoint === "string" &&
    p.checkpoint.length > 0, "invalid FC branch or checkpoint");
  assert(Array.isArray(p.paths) && p.paths.length > 0 && p.paths.length <= 64,
    "FC requires 1–64 selected files");
  const paths = p.paths.map(safePath);
  assert(new Set(paths).size === paths.length, "duplicate FC paths");
  // Stage all reads before changing anything; create a NEW branch, never edit the caller's branch.
  const changes = [];
  for (const path of paths) {
    const [source, target] = await Promise.all([
      statOrNull(lf.fs, p.checkpoint, path), statOrNull(lf.fs, p.branch, path)
    ]);
    assert(!source || source.type === "file", "FC only restores regular files: " + path);
    assert(!target || target.type === "file", "FC destination is not a regular file: " + path);
    if (source) {
      const content = await getText(lf.fs, p.checkpoint, path);
      changes.push({ op: "write", path, content });
    } else if (target) {
      changes.push({ op: "rm", path });
    }
  }
  const outputBranch = safeBranch("fc");
  const forked = await lf.branch.fork(outputBranch, p.branch);
  let result = { kind: "UpToDate" };
  if (changes.length) {
    // Atomic cross-file publication; conflicting branches are rejected by LayerFS.
    result = await lf.fs.apply(outputBranch, changes, "FC: restore selected paths from " + p.checkpoint);
  }
  return { branch: outputBranch, based_on: p.branch, checkpoint: p.checkpoint,
           paths, changes: changes.length, forked, result };
}

async function runAgent(lf, p) {
  assert(validName.test(p.id), "invalid task ID");
  assert(Array.isArray(p.argv) && p.argv.length > 0 && p.argv.length <= 128,
    "argv required");
  assert(Array.isArray(p.parents) && p.parents.every(x => typeof x === "string"),
    "invalid parent references");
  assert(typeof p.timeout_s === "number" && p.timeout_s > 0 && p.timeout_s <= 86400,
    "invalid timeout");
  let base = "main";
  if (p.parents.length > 0) {
    base = p.parents[0];
    for (const other of p.parents.slice(1)) {
      const mergeName = safeBranch("join");
      await lf.branch.merge(base, other, mergeName, "Merge dependency outputs for " + p.id);
      base = mergeName;
    }
  }
  const branch = safeBranch(p.id);
  await lf.branch.fork(branch, base);
  let sandbox = null, workspace = null, issue = null, value = null;
  try {
    const created = await lf.sandbox.create();
    sandbox = created.sandbox;
    workspace = await lf.workspace.mount(sandbox, branch);
    // Run inside LayerFS's Docker sandbox. GNU timeout in the runtime image is mandatory.
    const cmd = p.argv.map(shellEscape).join(" ");
    const bounded = "timeout --signal=TERM --kill-after=2s " +
      Math.ceil(p.timeout_s) + "s sh -c " + shellEscape("exec " + cmd);
    const executed = await lf.workspace.exec(workspace, bounded, "AgentOS " + p.id);
    const exit = executed.exitCode;
    assert(Number.isInteger(exit), "LayerFS returned no exitCode");
    const good = exit === 0;
    const committed = good ? await lf.workspace.commit(workspace, "AgentOS success: " + p.id) : null;
    value = { exit_code: exit,
      stdout: (executed.stdout ?? "").slice(0, MAX_OUTPUT),
      stderr: (executed.stderr ?? "").slice(0, MAX_OUTPUT),
      branch: good ? branch : null,
      commit: committed?.commit?.id ?? committed?.head ?? null,
      error: good ? "" : (exit === 124 ? "sandbox wall timeout" : "sandbox exit " + exit) };
  } catch (error) {
    issue = error;
  } finally {
    if (workspace) {
      try { await lf.workspace.unmount(workspace, !!issue || !value || value.exit_code !== 0); }
      catch (e) { issue ??= e; }
    }
    if (sandbox) {
      try { await lf.sandbox.close(sandbox); }
      catch (e) { issue ??= e; }
    }
  }
  if (issue) throw issue;
  return value;
}

async function readInput() {
  const bytes = [];
  let total = 0;
  for await (const block of process.stdin) {
    total += block.length;
    if (total > MAX_REQUEST) throw new Error("LayerFS bridge request too large");
    bytes.push(block);
  }
  const value = JSON.parse(Buffer.concat(bytes).toString("utf8"));
  assert(value && typeof value === "object" && !Array.isArray(value), "invalid request");
  return value;
}

try {
  const input = await readInput();
  assert(["run", "fc"].includes(input.action), "unsupported LayerFS bridge action");
  const modulePath = process.env.LAYERFS_AGENT_MODULE;
  // Local SDK checkout can be linked with node_modules; no npm-registry dependency.
  const pkg = modulePath ? await import(pathToFileURL(modulePath).href) : await import("@layerfs/agent");
  assert(typeof pkg.LayerFS?.open === "function", "LayerFS 1.1.0 SDK not found");
  const project = process.env.LAYERFS_PROJECT;
  assert(typeof project === "string" && project.length > 0, "LAYERFS_PROJECT missing");
  const layerfs = await pkg.LayerFS.open(project);
  try {
    const value = input.action === "run"
      ? await runAgent(layerfs, input) : await fcRestore(layerfs, input);
    process.stdout.write(JSON.stringify({ ok: true, value }) + "\n");
  } finally {
    await layerfs.close();
  }
} catch (error) {
  process.stdout.write(JSON.stringify({
    ok: false, code: error?.code || "BridgeError",
    error: String(error?.message ?? error).slice(0, 4096)
  }) + "\n");
  process.exitCode = 1;
}
