"""Pure-stdlib mock MCP server for testing baize.mcp.MCPClient.

It speaks NDJSON JSON-RPC over stdio exactly like a real MCP server:
  - initialize      -> protocolVersion + capabilities
  - notifications/* -> ignored (no response)
  - tools/list      -> two tools: echo (string) and add (ints)
  - tools/call      -> runs the named tool, returns text content

Test flags:
  --die-on-call     exit(1) instead of answering tools/call (crash path)
  --stderr MSG      write MSG to stderr at startup (stderr capture path)
  --garbage-first   emit one malformed line before the protocol (skip path)
  --hang-after-init sleep(60) after answering initialize (timeout path)
  --image-result    tools/call returns a non-text (image) content block
  --missing-name    tools/list includes one entry without a "name"
"""
import json
import sys
import time


def _write(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main():
    flags = sys.argv[1:]
    die_on_call = "--die-on-call" in flags
    garbage_first = "--garbage-first" in flags
    hang_after_init = "--hang-after-init" in flags
    image_result = "--image-result" in flags
    missing_name = "--missing-name" in flags
    stderr_msg = None
    if "--stderr" in flags:
        i = flags.index("--stderr")
        if i + 1 < len(flags):
            stderr_msg = flags[i + 1]

    if stderr_msg is not None:
        sys.stderr.write(stderr_msg + "\n")
        sys.stderr.flush()
    if garbage_first:
        sys.stdout.write("not-json-garbage\n")
        sys.stdout.flush()

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = msg.get("method")
        mid = msg.get("id")

        if method == "initialize":
            _write({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mock", "version": "1.0"},
            }})
            if hang_after_init:
                time.sleep(60)
        elif method == "notifications/initialized":
            continue  # notifications carry no id and expect no response
        elif method == "tools/list":
            tools = [
                {
                    "name": "echo",
                    "description": "Echo the message back.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                        "required": ["message"],
                    },
                },
                {
                    "name": "add",
                    "description": "Add two integers.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "a": {"type": "integer"},
                            "b": {"type": "integer"},
                        },
                        "required": ["a", "b"],
                    },
                },
            ]
            if missing_name:
                tools.append({"description": "no name", "inputSchema": {}})
            _write({"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}})
        elif method == "tools/call":
            if die_on_call:
                sys.exit(1)  # crash instead of answering -> fail-closed test
            params = msg.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            if name == "echo":
                content = [{"type": "text", "text": f"echo: {args.get('message', '')}"}]
                if image_result:
                    content.append({"type": "image", "data": "BASE64AAA"})
                _write({"jsonrpc": "2.0", "id": mid, "result": {
                    "content": content, "isError": False}})
            elif name == "add":
                res = int(args.get("a", 0)) + int(args.get("b", 0))
                _write({"jsonrpc": "2.0", "id": mid, "result": {
                    "content": [{"type": "text", "text": str(res)}],
                    "isError": False,
                }})
            else:
                _write({"jsonrpc": "2.0", "id": mid, "result": {
                    "content": [{"type": "text",
                                 "text": f"unknown tool {name}"}],
                    "isError": True,
                }})
        # unknown methods / stray notifications are silently ignored


if __name__ == "__main__":
    main()
