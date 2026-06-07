import * as vscode from "vscode";
import { CrickitServer } from "./server";

let server: CrickitServer | null = null;

export function activate(context: vscode.ExtensionContext): void {
  const output = vscode.window.createOutputChannel("Crickit");
  context.subscriptions.push(output);

  const version = (context.extension.packageJSON as { version?: string }).version ?? "unknown";
  output.appendLine(`Crickit extension v${version} activating...`);

  server = new CrickitServer(output);
  server.start();

  context.subscriptions.push(
    vscode.debug.registerDebugAdapterTrackerFactory("*", server.trackerFactory())
  );
}

export function deactivate(): void {
  if (server) {
    server.stop();
    server = null;
  }
}
