# CLI UI V2

## Requirements

1. Use the full layout (header + bottom bar) described in @CLI-UI-Design.md:
  - User messages start with  ❯ 
  - System messages (like /help) start with ⏺ in green
  - LLM responses start with ⏺ in blue
  - User, system, and LLM responses are separated by horizontal lines.
  - Header shows device, online/offline, model, and cwd.
  - Bottom bar shows hints on the left and voice status on the right.
2. Tool calls shall be inline with the chat, in the order the LLM called them. 
3. Responses are shown as they arrive. No waiting until all tool calls are done to show the first message. 
4. Tool calls can be expanded or collapsed (see the app inside the folder `mistral-vibe` for an example).