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

interface SetBreakpointParams {
  file: string;
  line: number;
  condition?: string;
}

interface BreakpointInfo {
  id: string;
  file: string;
  line: number;
  verified: boolean;
}

interface RemoveBreakpointParams {
  id: string;
}

interface ContinueParams {
  sessionId: string;
  threadId: number;
}

interface StackTraceParams {
  sessionId: string;
  threadId: number;
}

interface ScopesParams {
  sessionId: string;
  frameId: number;
}

interface VariablesParams {
  sessionId: string;
  variablesReference: number;
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

// file:line → SourceBreakpoint
const breakpointMap = new Map<string, vscode.SourceBreakpoint>();

function bpKey(file: string, line: number): string {
  return `${file}:${line}`;
}

export class CrickitServer {
  private server: net.Server | null = null;
  private connections: MessageConnection[] = [];
  private output: vscode.OutputChannel;

  constructor(output: vscode.OutputChannel) {
    this.output = output;
  }

  broadcast(method: string, params: unknown): void {
    const notification = JSON.stringify({ jsonrpc: "2.0", method, params });
    const body = Buffer.from(notification);
    const header = `Content-Length: ${body.length}\r\n\r\n`;
    for (const conn of this.connections) {
      try {
        (conn as any).sendNotification(method, params);
      } catch {
        // connection may have closed
      }
    }
  }

  /** Registers an RPC request handler that logs the call and its outcome to the output channel. */
  private onRequest<P, R>(
    conn: MessageConnection,
    method: string,
    handler: (params: P) => R | Promise<R>
  ): void {
    conn.onRequest(method, async (params: P): Promise<R> => {
      this.output.appendLine(`→ ${method} ${JSON.stringify(params)}`);
      try {
        const result = await handler(params);
        this.output.appendLine(`← ${method} ok`);
        return result;
      } catch (err: any) {
        this.output.appendLine(`✗ ${method} error: ${err?.message ?? err}`);
        throw err;
      }
    });
  }

  trackerFactory(): vscode.DebugAdapterTrackerFactory {
    const self = this;
    return {
      createDebugAdapterTracker(
        session: vscode.DebugSession
      ): vscode.DebugAdapterTracker {
        return {
          onDidSendMessage(message: any): void {
            if (message.type !== "event") return;
            switch (message.event) {
              case "stopped":
                self.broadcast("debug/stopped", {
                  sessionId: session.id,
                  threadId: message.body.threadId,
                  reason: message.body.reason,
                  description: message.body.description,
                });
                break;
              case "terminated":
                self.broadcast("debug/terminated", { sessionId: session.id });
                break;
              case "continued":
                self.broadcast("debug/continued", {
                  sessionId: session.id,
                  threadId: message.body.threadId,
                });
                break;
              case "output":
                self.broadcast("debug/output", {
                  sessionId: session.id,
                  category: message.body.category,
                  output: message.body.output,
                });
                break;
            }
          },
        };
      },
    };
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

      this.onRequest(conn,
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

      this.onRequest(conn, "debug/sessions", (): DebugSessionInfo[] => {
        const session = vscode.debug.activeDebugSession;
        if (!session) {
          return [];
        }
        return [{ id: session.id, name: session.name, type: session.type }];
      });

      this.onRequest(conn,
        "debug/setBreakpoint",
        (params: SetBreakpointParams): BreakpointInfo => {
          const uri = vscode.Uri.file(params.file);
          const pos = new vscode.Position(params.line - 1, 0);
          const location = new vscode.Location(uri, pos);
          const condition = params.condition;
          const bp = condition
            ? new vscode.SourceBreakpoint(location, true, condition)
            : new vscode.SourceBreakpoint(location, true);
          vscode.debug.addBreakpoints([bp]);
          const key = bpKey(params.file, params.line);
          breakpointMap.set(key, bp);
          return {
            id: key,
            file: params.file,
            line: params.line,
            verified: true,
          };
        }
      );

      this.onRequest(conn,
        "debug/removeBreakpoint",
        (params: RemoveBreakpointParams): void => {
          const bp = breakpointMap.get(params.id);
          if (bp) {
            vscode.debug.removeBreakpoints([bp]);
            breakpointMap.delete(params.id);
          }
        }
      );

      this.onRequest(conn, "debug/listBreakpoints", (): BreakpointInfo[] => {
        return Array.from(breakpointMap.entries()).map(([id, bp]) => {
          const loc = bp.location;
          return {
            id,
            file: loc.uri.fsPath,
            line: loc.range.start.line + 1,
            verified: bp.enabled,
          };
        });
      });

      this.onRequest(conn,
        "debug/continue",
        async (params: ContinueParams): Promise<void> => {
          const session = vscode.debug.activeDebugSession;
          if (!session) throw new Error("No active debug session");
          await session.customRequest("continue", { threadId: params.threadId });
        }
      );

      this.onRequest(conn,
        "debug/next",
        async (params: ContinueParams): Promise<void> => {
          const session = vscode.debug.activeDebugSession;
          if (!session) throw new Error("No active debug session");
          await session.customRequest("next", { threadId: params.threadId });
        }
      );

      this.onRequest(conn,
        "debug/stepIn",
        async (params: ContinueParams): Promise<void> => {
          const session = vscode.debug.activeDebugSession;
          if (!session) throw new Error("No active debug session");
          await session.customRequest("stepIn", { threadId: params.threadId });
        }
      );

      this.onRequest(conn,
        "debug/stepOut",
        async (params: ContinueParams): Promise<void> => {
          const session = vscode.debug.activeDebugSession;
          if (!session) throw new Error("No active debug session");
          await session.customRequest("stepOut", { threadId: params.threadId });
        }
      );

      this.onRequest(conn,
        "debug/stackTrace",
        async (params: StackTraceParams): Promise<object[]> => {
          const session = vscode.debug.activeDebugSession;
          if (!session) throw new Error("No active debug session");
          const result = await session.customRequest("stackTrace", {
            threadId: params.threadId,
            startFrame: 0,
            levels: 20,
          });
          return result.stackFrames.map((f: any) => ({
            id: f.id,
            name: f.name,
            source: f.source?.path ?? f.source?.name ?? "",
            line: f.line,
            column: f.column,
          }));
        }
      );

      this.onRequest(conn,
        "debug/scopes",
        async (params: ScopesParams): Promise<object[]> => {
          const session = vscode.debug.activeDebugSession;
          if (!session) throw new Error("No active debug session");
          const result = await session.customRequest("scopes", {
            frameId: params.frameId,
          });
          return result.scopes.map((s: any) => ({
            name: s.name,
            variablesReference: s.variablesReference,
            expensive: s.expensive,
          }));
        }
      );

      this.onRequest(conn,
        "debug/variables",
        async (params: VariablesParams): Promise<object[]> => {
          const session = vscode.debug.activeDebugSession;
          if (!session) throw new Error("No active debug session");
          const result = await session.customRequest("variables", {
            variablesReference: params.variablesReference,
          });
          return result.variables.map((v: any) => ({
            name: v.name,
            value: v.value,
            type: v.type ?? "",
            variablesReference: v.variablesReference,
          }));
        }
      );

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
