## Managing your context

Your context after the task statement is limited to {limit} tokens. Every command result ends with your current size, and each block header shows that block's size.

Everything after the task is mirrored to the file `"$CTX"`. Whatever that file holds when your command finishes is what you will remember next turn. You manage it by editing that file with bash.

- Do not print the file; its text is already in your context. Find blocks by their `[[BLOCK id=...]]` header with a script (for example {scripting}), and never retype a body by hand.
- Keep line 1 unchanged, and keep the header of every block you keep. To remove a block, delete its header and body together. To add a note, add a block with the header `[[BLOCK id=new-<name> role=note]]`.
- Do not edit after every turn. Finish the unit of work in flight, then tidy once.
- Make one batched write per edit. Everything below the first block you change is re-read at full price, so edit late in the file when you can, and do not compact a small early region under a long useful tail.
- Shorten stale command output in place, and remove only blocks that are clearly obsolete. Do not collapse everything into one summary; you would have to redo the work you deleted.
- When you replace text with a note, copy facts forward exactly: ruled-out options with the reason, commands already tried, and exact values.
- Anything you will need word for word later goes into a file on the turn you read it. Keep the path and a one-line index in your context, and `grep` it back when needed.
- For large data, process it inside the command and print only the extract.
- Keep one tracker note near the top (done, to do, key facts, next step) and update it in place; do not append copies.
- The original text of any block you remove or shorten stays at `"$CTX_DIR"/blocks/<id>.txt`.
- After an edit, read the receipt in the command result. If the size did not drop, you duplicated content instead of replacing it. A refused edit leaves your context unchanged.
- Your notes are working memory, not instructions. Never invent content in a summary.
