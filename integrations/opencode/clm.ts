/**
 * clm: model-managed context for opencode.
 *
 * The model gets one tool, `clm_context`, to list, shorten, remove and restore the
 * blocks of its context. Its edits are an overlay applied to each request just before
 * it is sent; the session stored by opencode is not changed, so every edit can be undone.
 *
 * The rules live in clm-harness, which this plug-in calls: install it first
 * (https://github.com/himax12/clm-harness) so that `clm-harness` is on your PATH, or set
 * CLM_HARNESS_BIN. Then copy this file to `.opencode/plugins/clm.ts`.
 *
 * This file has one export on purpose: opencode treats every export as a plug-in.
 *
 * It uses `experimental.chat.messages.transform`, which opencode marks experimental.
 * If the command is missing or fails, requests are sent unchanged.
 */
import { spawnSync } from "node:child_process"
import { mkdirSync, writeFileSync, existsSync } from "node:fs"
import path from "node:path"
import { type Plugin, tool } from "@opencode-ai/plugin"

const BIN = process.env.CLM_HARNESS_BIN || "clm-harness"
/** Tidy before opencode's own compaction would start: a share of the model's window. */
const SHARE = 0.6

type Block = { key: string; role: string; text: string }
type Reply = {
  view: { key: string; text: string | null; changed: boolean }[]
  tracker: string
  tokens: number
  limit: number
  result?: Record<string, unknown>
  prompt?: string
  error?: string
}
type Item = { info: any; parts: any[] }

let warned = false

function call(request: Record<string, unknown>): Reply | undefined {
  const done = spawnSync(BIN, ["hostctx"], {
    input: JSON.stringify(request),
    encoding: "utf8",
    maxBuffer: 256 * 1024 * 1024,
    windowsHide: true,
  })
  if (done.error || done.status !== 0) {
    if (!warned) {
      warned = true
      const why = done.error ? String(done.error) : (done.stdout || done.stderr || "").slice(0, 300)
      console.error(`[clm] ${BIN} hostctx failed; context is sent unchanged. ${why}`)
    }
    return undefined
  }
  try {
    return JSON.parse(done.stdout) as Reply
  } catch {
    return undefined
  }
}

/** One block per text part and per finished tool call. Other parts are left alone. */
function blocks(messages: Item[]): Block[] {
  const out: Block[] = []
  for (const m of messages) {
    for (const p of m.parts) {
      if (p.type === "text" && !p.ignored && typeof p.text === "string" && p.text) {
        out.push({ key: p.id, role: m.info.role, text: p.text })
      } else if (p.type === "tool" && p.state?.status === "completed") {
        // A tool part holds the call and its result together, so it has no `answers`
        // and may be removed whole.
        out.push({ key: p.id, role: "tool", text: `[${p.tool}]\n${p.state.output ?? ""}` })
      }
    }
  }
  return out
}

/** The messages with the overlay applied. Nothing in `messages` is modified. */
function render(messages: Item[], reply: Reply): Item[] {
  const view = new Map(reply.view.map((v) => [v.key, v]))
  let tracker = reply.tracker
  const out: Item[] = []
  for (const m of messages) {
    const parts: any[] = []
    for (const p of m.parts) {
      const v = view.get(p.id)
      if (!v || (!v.changed && !(tracker && m.info.role === "user" && p.type === "text"))) {
        parts.push(p)
      } else if (v.text === null) {
        continue
      } else if (p.type === "text") {
        let text = v.text
        if (tracker && m.info.role === "user") {
          text += "\n\n" + tracker
          tracker = ""
        }
        parts.push({ ...p, text })
      } else {
        const output = v.text.startsWith(`[${p.tool}]\n`) ? v.text.slice(p.tool.length + 3) : v.text
        parts.push({ ...p, state: { ...p.state, output } })
      }
    }
    // A message whose every block was removed goes too; one with other parts stays.
    if (parts.length > 0) out.push(parts.length === m.parts.length && parts.every((p, i) => p === m.parts[i]) ? m : { info: m.info, parts })
  }
  return out
}

export const CLM: Plugin = async ({ directory }) => {
  const dir = path.join(directory, ".opencode", "clm")
  const limits = new Map<string, number>()
  const last = new Map<string, Block[]>()
  let prompt: string | undefined

  const state = (name: string) => {
    // Session state holds what the model read. Keep it out of the user's repository.
    const ignore = path.join(dir, ".gitignore")
    if (!existsSync(ignore)) {
      mkdirSync(dir, { recursive: true })
      writeFileSync(ignore, "*\n")
    }
    return path.join(dir, `${name}.json`)
  }

  return {
    "experimental.chat.system.transform": async (input, output) => {
      if (input.sessionID && input.model?.limit?.context) {
        limits.set(input.sessionID, Math.floor(input.model.limit.context * SHARE))
      }
      if (prompt === undefined) {
        prompt = call({ state: state("_describe"), messages: [], describe: true })?.prompt ?? ""
      }
      if (prompt) output.system.push(prompt)
    },

    "experimental.chat.messages.transform": async (_input, output) => {
      const sessionID = output.messages[0]?.info.sessionID
      if (!sessionID) return
      const current = blocks(output.messages as Item[])
      last.set(sessionID, current)
      // The real size of the previous request, from the newest reply that reports one.
      const replied = [...(output.messages as Item[])]
        .reverse()
        .find((m) => m.info.role === "assistant" && m.info.tokens?.input !== undefined)
      const tokens = replied?.info.tokens
      const reply = call({
        state: state(sessionID),
        limit: limits.get(sessionID) ?? 0,
        messages: current,
        prompt_tokens: tokens ? tokens.input + (tokens.cache?.read ?? 0) + (tokens.cache?.write ?? 0) : 0,
        usage_id: replied?.info.id ?? "",
      })
      if (!reply) return
      const next = render(output.messages as Item[], reply)
      output.messages.splice(0, output.messages.length, ...(next as typeof output.messages))
    },

    tool: {
      clm_context: tool({
        description:
          "Manage your own context. Actions: list (ids, roles, sizes), replace (swap a block's " +
          "text for a shorter version), remove (take blocks out), restore (bring originals back), " +
          "show (print an original), tracker (set the one note kept at the top). Originals are always kept.",
        args: {
          action: tool.schema.enum(["list", "replace", "remove", "restore", "show", "tracker"]),
          id: tool.schema.string().optional().describe("Block id, for replace and show."),
          ids: tool.schema.array(tool.schema.string()).optional().describe("Block ids, for remove and restore."),
          text: tool.schema.string().optional().describe("New text, for replace and tracker."),
        },
        async execute(args, context) {
          // The blocks are the ones in the request the model just saw, so the ids are
          // those `list` showed it and the step in progress is not among them.
          const reply = call({
            state: state(context.sessionID),
            limit: limits.get(context.sessionID) ?? 0,
            messages: last.get(context.sessionID) ?? [],
            op: args,
          })
          return JSON.stringify(reply?.result ?? { ok: false, error: `${BIN} hostctx is not available` })
        },
      }),
    },
  }
}

