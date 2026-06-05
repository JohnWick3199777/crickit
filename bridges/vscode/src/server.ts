import * as net from "net";
import * as fs from "fs";
import * as path from "path";
import { createMessageConnection } from "vscode-jsonrpc/node";
import type { MessageConnection } from "vscode-jsonrpc";
import * as vscode from "vscode";

const SOCKET_DIR = path.join(
  process.env.HOME ?? process.env.USERPROFILE ?? "~",
  ".crickit"
);
const SOCKET_PATH = path.join(SOCKET_DIR, "bridge.sock");

interface DebugSessionInfo {
  id: string;
  name: string;
  type: string;
}

interface LaunchParams {
  program: string;
  type?: string;
  args?: string[];
  stopOnEntry?: boolean;
}

function inferDebugType(program: string): string {
  const ext = path.extname(program).toLowerCase();
  switch (ext) {
    case ".py":
      return "debugpy";
    case ".js":
      return "node";
    default:
      throw new Error(`Cannot infer debug type for extension: ${ext || "(none)"}`);
  }
}

export class CrickitServer {
  private server: net.Server | null = null;
  private connections: MessageConnection[] = [];
  private output: vscode.OutputChannel;

  constructor(output: vscode.OutputChannel) {
    this.output = output;
  }

  start(): void {
    if (!fs.existsSync(SOCKET_DIR)) {
      fs.mkdirSync(SOCKET_DIR, { recursive: true });
    }
    if (fs.existsSync(SOCKET_PATH)) {
      fs.unlinkSync(SOCKET_PATH);
    }

    this.server = net.createServer((socket) => {
      const conn = createMessageConnection(socket, socket);
      this.connections.push(conn);

      conn.onRequest(
        "debug/launch",
        (params: LaunchParams): Promise<DebugSessionInfo> => {
          const debugType = params.type ?? inferDebugType(params.program);
          const config: vscode.DebugConfiguration = {
            type: debugType,
            name: path.basename(params.program),
            request: "launch",
            program: params.program,
            args: params.args ?? [],
            stopOnEntry: params.stopOnEntry ?? false,
          };

          return new Promise((resolve, reject) => {
            const disposable = vscode.debug.onDidStartDebugSession((session) => {
              disposable.dispose();
              resolve({ id: session.id, name: session.name, type: session.type });
            });

            vscode.debug.startDebugging(undefined, config).then(
              (started) => {
                if (!started) {
                  disposable.dispose();
                  reject(new Error("startDebugging returned false"));
                }
              },
              (err: Error) => {
                disposable.dispose();
                reject(err);
              }
            );
          });
        }
      );

      conn.onRequest("debug/sessions", (): DebugSessionInfo[] => {
        const session = vscode.debug.activeDebugSession;
        if (!session) {
          return [];
        }
        return [{ id: session.id, name: session.name, type: session.type }];
      });

      conn.onClose(() => {
        this.connections = this.connections.filter((c) => c !== conn);
      });

      conn.listen();
    });

    this.server.listen(SOCKET_PATH, () => {
      this.output.appendLine(`Crickit bridge listening on ${SOCKET_PATH}`);
    });

    this.server.on("error", (err) => {
      this.output.appendLine(`Crickit bridge error: ${err.message}`);
    });
  }

  stop(): void {
    for (const conn of this.connections) {
      conn.dispose();
    }
    this.connections = [];
    if (this.server) {
      this.server.close();
      this.server = null;
    }
    if (fs.existsSync(SOCKET_PATH)) {
      fs.unlinkSync(SOCKET_PATH);
    }
    this.output.appendLine("Crickit bridge stopped.");
  }
}
