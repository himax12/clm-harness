// Drives the compiled plug-in the way opencode would, with a synthetic session.
// No model call is made.
import assert from "node:assert/strict"
import { mkdtempSync, existsSync, readFileSync } from "node:fs"
import os from "node:os"
import path from "node:path"
import { CLM } from "./out/clm.js"

const directory = mkdtempSync(path.join(os.tmpdir(), "oc-clm-"))
const hooks = await CLM({ directory })
assert.deepEqual(Object.keys(hooks).sort(),
  ["experimental.chat.messages.transform", "experimental.chat.system.transform", "tool"])

const sessionID = "ses_1"
const text = (id, messageID, t) => ({ id, sessionID, messageID, type: "text", text: t })
const toolPart = (id, messageID, callID, output) => ({
  id, sessionID, messageID, type: "tool", callID, tool: "bash",
  state: { status: "completed", input: { command: "cat app.py" }, output, title: "", metadata: {}, time: { start: 1, end: 2 } },
})
const messages = [
  { info: { id: "m1", sessionID, role: "user" }, parts: [text("p1", "m1", "Find the bug in app.py.")] },
  { info: { id: "m2", sessionID, role: "assistant" }, parts: [
    { id: "s1", sessionID, messageID: "m2", type: "step-start" },
    text("p2", "m2", "Reading the file."),
    toolPart("p3", "m2", "call_1", "line of code\n".repeat(3000)),
  ] },
  { info: { id: "m3", sessionID, role: "assistant" }, parts: [toolPart("p4", "m3", "call_2", "ok")] },
  { info: { id: "m4", sessionID, role: "user" }, parts: [text("p5", "m4", "Now fix it.")] },
]
const frozen = JSON.stringify(messages)

const system = { system: ["You are opencode."] }
await hooks["experimental.chat.system.transform"]({ sessionID, model: { limit: { context: 100_000, output: 8000 } } }, system)
assert.equal(system.system.length, 2)
assert.match(system.system[1], /clm_context/)
console.log("system prompt: guide added")

const run = async () => {
  const output = { messages: [...messages] }
  await hooks["experimental.chat.messages.transform"]({}, output)
  return output.messages
}
let sent = await run()
assert.equal(JSON.stringify(messages), frozen, "the session's own messages were modified")
assert.equal(sent.length, 4)
assert.ok(sent.every((m, i) => m === messages[i]), "untouched messages must be the same objects")
console.log("first request: sent unchanged")

const ctx = { sessionID, messageID: "m5", agent: "build", directory, worktree: directory }
const tool = hooks.tool.clm_context
const listing = JSON.parse(await tool.execute({ action: "list" }, ctx))
console.log("list:", listing.blocks.map((b) => [b.id, b.role, b.state, b.tokens]))
assert.deepEqual(listing.blocks.map((b) => b.role), ["user", "assistant", "tool", "tool", "user"])
const big = listing.blocks[2].id

const refused = JSON.parse(await tool.execute({ action: "replace", id: listing.blocks[0].id, text: "do x" }, ctx))
assert.equal(refused.ok, false)
const receipt = JSON.parse(await tool.execute({ action: "replace", id: big, text: "app.py read; bug on line 3" }, ctx))
assert.ok(receipt.ok && receipt.after_tokens < receipt.before_tokens, JSON.stringify(receipt))
console.log("replace receipt:", receipt)
JSON.parse(await tool.execute({ action: "remove", ids: [listing.blocks[3].id] }, ctx))
JSON.parse(await tool.execute({ action: "tracker", text: "next: fix line 3" }, ctx))

sent = await run()
assert.equal(JSON.stringify(messages), frozen, "the session's own messages were modified")
assert.equal(sent.length, 3, "the message whose only block was removed should go")
assert.equal(sent[1].parts[2].state.output, "app.py read; bug on line 3")
assert.equal(sent[1].parts[2].callID, "call_1")
assert.equal(sent[1].parts[0].type, "step-start", "parts that are not blocks are kept")
assert.ok(sent[0].parts[0].text.endsWith("[context tracker]\nnext: fix line 3"))
assert.equal(sent[2], messages[3], "an untouched message is the same object")
console.log("second request: output replaced, emptied message dropped, tracker added, session untouched")

JSON.parse(await tool.execute({ action: "restore", ids: [big] }, ctx))
sent = await run()
assert.ok(sent[1].parts[2].state.output.startsWith("line of code"))
console.log("restore: the original is back")

assert.ok(existsSync(path.join(directory, ".opencode", "clm", `${sessionID}.json`)))
assert.equal(readFileSync(path.join(directory, ".opencode", "clm", ".gitignore"), "utf8"), "*\n")

// With the command missing, requests go out unchanged.
process.env.CLM_HARNESS_BIN = "definitely-not-a-command"
const broken = await (await import("./out/clm.js?missing")).CLM({ directory })
const output = { messages: [...messages] }
await broken["experimental.chat.messages.transform"]({}, output)
assert.ok(output.messages.every((m, i) => m === messages[i]))
console.log("missing command: fails open")
console.log("ALL OPENCODE CHECKS PASSED")
