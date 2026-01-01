/**
 * Deno host script for Pyodide sandbox.
 * 
 * This script:
 * 1. Loads Pyodide (Python in WebAssembly)
 * 2. Sets up bridge communication via stdin/stdout
 * 3. Executes Python code with injected proxy objects
 * 4. Routes skill calls back to Python host
 */

// @ts-ignore - Deno types
const { stdin, stdout, stderr } = Deno;

// Globals
let pyodide: any = null;
const pendingCalls: Map<string, { resolve: (v: any) => void; reject: (e: any) => void }> = new Map();

// ============================================================================
// Logging (to stderr so it doesn't interfere with bridge)
// ============================================================================

function log(msg: string) {
  const encoder = new TextEncoder();
  stderr.writeSync(encoder.encode(`[Sandbox] ${msg}\n`));
}

// ============================================================================
// Bridge Communication
// ============================================================================

const encoder = new TextEncoder();
const decoder = new TextDecoder();

function sendMessage(message: object) {
  const line = JSON.stringify(message) + "\n";
  stdout.writeSync(encoder.encode(line));
}

// Read buffer for stdin
let readBuffer = "";

async function readLine(): Promise<string> {
  const reader = stdin.readable.getReader();
  
  while (!readBuffer.includes("\n")) {
    const { value, done } = await reader.read();
    if (done) {
      reader.releaseLock();
      throw new Error("stdin closed");
    }
    readBuffer += decoder.decode(value);
  }
  
  reader.releaseLock();
  
  const newlineIndex = readBuffer.indexOf("\n");
  const line = readBuffer.slice(0, newlineIndex);
  readBuffer = readBuffer.slice(newlineIndex + 1);
  return line;
}

// ============================================================================
// Bridge Call Handler (called from Python inside sandbox)
// ============================================================================

function bridgeCall(path: string, args: any[], kwargs: object): Promise<any> {
  return new Promise((resolve, reject) => {
    const id = crypto.randomUUID();
    
    // Store pending call
    pendingCalls.set(id, { resolve, reject });
    
    // Send call request to Python host
    sendMessage({
      type: "call",
      id: id,
      data: { path, args, kwargs }
    });
  });
}

// ============================================================================
// Pyodide Setup
// ============================================================================

async function initPyodide() {
  log("Loading Pyodide...");
  
  // Dynamic import of Pyodide
  // @ts-ignore
  const { loadPyodide } = await import("npm:pyodide@0.26.4");
  
  pyodide = await loadPyodide({
    // Pyodide options
    stdout: (text: string) => {
      // Capture Python stdout for later
      if ((globalThis as any)._pythonStdout !== undefined) {
        (globalThis as any)._pythonStdout += text + "\n";
      }
    },
    stderr: (text: string) => {
      log(`[Python stderr] ${text}`);
    },
  });
  
  // Set up the bridge call function that Python code can use
  pyodide.globals.set("_js_bridge_call", bridgeCall);
  
  log("Pyodide loaded successfully");
}

// ============================================================================
// Code Execution
// ============================================================================

async function executeCode(id: string, code: string, proxyCode: string) {
  try {
    // Reset stdout capture
    (globalThis as any)._pythonStdout = "";
    
    // Inject proxy code first
    if (proxyCode) {
      await pyodide.runPythonAsync(proxyCode);
    }
    
    // Set up stdout capture in Python
    await pyodide.runPythonAsync(`
import sys
from io import StringIO
_stdout_capture = StringIO()
_original_stdout = sys.stdout
sys.stdout = _stdout_capture
`);
    
    // Execute user code
    await pyodide.runPythonAsync(code);
    
    // Get captured output
    const output = await pyodide.runPythonAsync(`
sys.stdout = _original_stdout
_stdout_capture.getvalue()
`);
    
    // Send completion
    sendMessage({
      type: "complete",
      id: id,
      data: { output: output || "" }
    });
    
  } catch (e: any) {
    // Send error
    sendMessage({
      type: "error",
      id: id,
      data: { error: String(e) }
    });
  }
}

// ============================================================================
// Message Handler
// ============================================================================

async function handleMessage(message: any) {
  const { type, id, data } = message;
  
  if (type === "execute") {
    // Execute Python code
    await executeCode(id, data.code, data.proxy);
    
  } else if (type === "result") {
    // Result from a skill call
    const pending = pendingCalls.get(id);
    if (pending) {
      pending.resolve(data.value);
      pendingCalls.delete(id);
    }
    
  } else if (type === "error") {
    // Error from a skill call
    const pending = pendingCalls.get(id);
    if (pending) {
      pending.reject(new Error(data.error));
      pendingCalls.delete(id);
    }
    
  } else {
    log(`Unknown message type: ${type}`);
  }
}

// ============================================================================
// Main Loop
// ============================================================================

async function main() {
  try {
    // Initialize Pyodide
    await initPyodide();
    
    // Signal ready
    sendMessage({ type: "ready", id: "0", data: {} });
    console.log("READY"); // This goes to stdout for the Python process to detect
    
    // Message loop
    while (true) {
      try {
        const line = await readLine();
        const message = JSON.parse(line);
        await handleMessage(message);
      } catch (e: any) {
        if (e.message === "stdin closed") {
          log("stdin closed, exiting");
          break;
        }
        log(`Error handling message: ${e}`);
      }
    }
  } catch (e) {
    log(`Fatal error: ${e}`);
    Deno.exit(1);
  }
}

main();

