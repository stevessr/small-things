/**
 * Test double implementing only the public LayerFS 1.1.0 surface we consume.
 * NO real LayerFS Store, Docker, FUSE, or crash durability is tested here.
 */
const notFound = () => Object.assign(new Error("NoSuchPath"), { code: "NoSuchPath" });
export class LayerFS {
  static async init(name, source) {
    const instance = await LayerFS.open(name);
    instance.created = { kind: "Initialized", project: name, layer: "L0", source };
    return instance;
  }
  static async open(name) {
    if (name !== "agentos-test") throw new Error("unexpected fake project");
    return new LayerFS();
  }
  branch = {
    list_commits: async branch => ({ items: [
      { id: "c2", message: "FC: tool-two" },
      { id: "c1", message: "FC: tool-one" }
    ], hasMore: false, branch }),
    fork: async (name, from) => ({ kind: "Forked", branch: name, from }),
    merge: async (a, b, name) => ({ kind: "Merged", branch: name, a, b })
  };
  fs = {
    stat: async (ref, path) => {
      if (ref.startsWith("ag-") &&
          path === "/.agentos/declarations/" + process.env.LAYERFS_FAKE_DECLARE_AGENT + ".json" &&
          process.env.LAYERFS_FAKE_DECLARATION !== undefined)
        return { type: "file", size: Buffer.byteLength(process.env.LAYERFS_FAKE_DECLARATION) };
      if (ref === "checkpoint") {
        if (path === "/a.txt") return { type: "file", size: 7 };
        throw notFound();
      }
      if (ref === "working") {
        if (path === "/a.txt" || path === "/gone.txt" || path === "/keep.txt")
          return { type: "file", size: 5 };
        throw notFound();
      }
      throw notFound();
    },
    read: async (ref, path) => {
      if (ref.startsWith("ag-") &&
          path === "/.agentos/declarations/" + process.env.LAYERFS_FAKE_DECLARE_AGENT + ".json" &&
          process.env.LAYERFS_FAKE_DECLARATION !== undefined)
        return { text: process.env.LAYERFS_FAKE_DECLARATION, nextLine: null,
                 truncated: false, lineTruncated: false };
      if (ref === "checkpoint" && path === "/a.txt")
        return { text: "before\n", nextLine: null, truncated: false, lineTruncated: false };
      throw notFound();
    },
    apply: async (branch, changes, message) => ({
      kind: "Committed", branch, changes, message,
      // This commit should never modify working, by construction.
      safe: branch !== "working", head: "commit-fc"
    })
  };
  sandbox = {
    create: async () => ({ sandbox: "1", image: "fake-image" }),
    close: async sandbox => ({ kind: "Closed", sandbox })
  };
  workspace = {
    mount: async (sandbox, branch) => ({ sandbox, path: "/workspaces/1", branch }),
    exec: async (_ws, command) => ({
      kind: "ok", exitCode: Number(process.env.LAYERFS_FAKE_EXIT || 0),
      stdout: command, stderr: "", truncated: false
    }),
    commit: async () => ({ kind: "Committed", head: "c1", commit: { id: "c1" } }),
    unmount: async (_ws, discard) => ({ kind: "Unmounted", discard })
  };
  async close() { return; }
}
