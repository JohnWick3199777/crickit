import * as vscode from "vscode";
import { CrickitServer } from "./server";

let server: CrickitServer | null = null;

export function activate(context: vscode.ExtensionContext): void {
  const output = vscode.window.createOutputChannel("Crickit");
  context.subscriptions.push(output);

  server = new CrickitServer(output);
  server.start();
}

export function deactivate(): void {
  if (server) {
    server.stop();
    server = null;
  }
}
