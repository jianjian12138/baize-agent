/**
 * Baize Studio VS Code & Cursor Sidecar Extension.
 * Connects directly to local Baize Studio runtime (http://127.0.0.1:8787).
 */
export function activate(context: any) {
  console.log("Baize Studio Assistant Extension is active!");

  // Command: Open Webview Studio
  const openStudioCmd = {
    dispose: () => {},
    execute: () => {
      const panel = {
        title: "Baize Studio 工作台",
        viewColumn: 2,
        webview: {
          html: `<iframe src="http://127.0.0.1:8787" style="width:100%;height:100vh;border:none;"></iframe>`
        }
      };
      console.log("Opened Baize Studio Panel");
    }
  };

  // Command: Inline Refactor & Causal Heal (Ctrl+K)
  const inlineRefactorCmd = {
    dispose: () => {},
    execute: async () => {
      console.log("Triggered Baize Inline Refactor & AST Causal Debugger");
    }
  };

  return { openStudioCmd, inlineRefactorCmd };
}

export function deactivate() {}
