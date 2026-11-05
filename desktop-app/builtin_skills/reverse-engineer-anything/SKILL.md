---
name: reverse-engineer-anything
description: Inspect shipped applications, binaries and runtime evidence using the bundled REA MCP server.
---

# Reverse Engineer Anything

For ordinary complete source-repository analysis, use normal file tools. When the question needs shipped artifacts, decompilation or runtime evidence, use mcp_list_tools(server="rea",query=...) to discover the installed server’s actual tools. Fetch the selected tool’s full input schema using tool_name, then call it with mcp_call_tool. Prefer static inspection for a supplied artifact; do not execute targets or attach to unrelated processes merely to inspect them. REA supports multiple target families, but deep native analysis may need separately installed engines. Preserve returned evidence, omissions and unknowns; distinguish static inference from observed runtime behavior. Large responses are retained at full_result_path; read the relevant saved evidence before making claims. Do not repeat a timed-out mutating operation blindly. Reconnect via the MCP panel if transport stopped. The server is pinned to rea-agents 6.8.0 and uses the app’s private Node runtime, without changing other client configurations. Native engines are not silently installed. Upstream project: https://github.com/morluto/rea (MIT); preserve its attribution and tool identity.
