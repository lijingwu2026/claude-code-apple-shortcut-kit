---
name: shortcut-spec
description: "Asks the user one question list up front about a planned Apple Shortcut (who uses it, what it must do, why), recommends how to meet each need, marks each requirement as feasible or not against the platform protocol, and writes specs/PRD.md as a draft for the user to approve, with stories and acceptance criteria in the shape shortcut-qa reads. Use when someone asks for a spec, PRD or requirements for a new shortcut, or before the first build of a shortcut product that has no specs/PRD.md."
when_to_use: "Requests to write, draft or review the spec or PRD of a shortcut in Apple Shortcuts before it is built, or to turn a shortcut idea into acceptance criteria. Also on these literal tokens: specs/PRD.md, PRD, acceptance criteria, Apple Shortcuts."
---

<!-- The idea of attaching a best guess to each interview question comes from the interview-me skill of addyosmani/agent-skills (MIT License). -->

# shortcut-spec — from a shortcut idea to an approved `specs/PRD.md`

The spec is a file, `specs/PRD.md` in the product folder (the folder the shortcut will be built in; the build looks for `specs/` there). A spec that exists only in the reply does not count.

Write nothing in the same message as a question, except the two messages in step 6.

## 1. Post the whole question list first

When the request names no problem or task for the shortcut, the first message asks only this, and the question list follows the answer:

```
What should the shortcut help with? Describe the problem or the task in a sentence or two.
```

Otherwise the first message is the question list. Send every question in one message, so none is forgotten midway. Where the user's request already answers a question, the guess restates that answer.

**Output 1 — the question list:**

```
Before I write the spec, here is everything I need to know. Answer in one reply; "yes" accepts a guess.
Answer what you can; say "go ahead" at any point and I'll put the rest under open questions.

1. Who will use it (you, or someone else), and in what situation does the need come up?
   My guess: <…>
2. What do you want it to get done, show or keep? One line per thing; each becomes a user story. This includes anything it must fit with that you already use or keep.
   My guess: <one line per thing>
3. Why does it matter: what problem does it solve today, and how will you know it worked?
   My guess: <…>
```

When an item counts as answered:

- **Who:** it names a concrete person and the situation.
- **What:** each thing can become a story with at least one acceptance criterion whose condition and result come from the user's words. A vague item such as "track my mood" is not answered yet: ask what they want to see or keep.
- **Why:** it names the problem today and one thing the user could see or check to know it worked.

The interview ends when every item meets its rule, is moved to section 6 (open questions) of the spec, or the user says to go ahead.

## 2. Ask only what is still unanswered

Each later message asks only the list items that do not yet meet their rule, each followed by `My guess: <…>`. When the interview ends, move every item still unanswered to section 6.

Before sending any question, check: does it ask what the user needs, or how the shortcut should do it? Red flags: which app stores the data, which actions to use, the trigger or automation type, the auth method, field names. When the user names a solution ("make it a 7:00 automation"), ask the need behind it. A system the user already keeps the data in is a need: record it under item 2.

## 3. Recommend the solution and mark the feasibility of every requirement

The answers fill the template's Goal section (who, why, success; the hard constraint is anything it must fit with), and each "what" becomes one story. Claude Code recommends the rest: the devices and entry point (section 1), where each value is stored (section 3), the feasibility verdicts (section 2) and the acceptance criteria, which come from the user's answer on how they will know it worked. Mark every recommendation `(unconfirmed default)` where it is used and list it in section 6 until the user approves the spec.

Read `${CLAUDE_PLUGIN_ROOT}/docs/apple_shortcuts_dev_protocol.md` §1 and §2 before recommending or marking. Recommend from everything §1.1 says a shortcut can reach (system apps, AI models, and any service with a web API, such as a Notion database the user already keeps), not only apps that have Shortcuts actions. Give each requirement one verdict: works / iPhone only / needs a workaround (name the workaround) / not a shortcut (an app is needed), and cite the protocol line it rests on.

- A requirement that must run unattended (a time-of-day automation, a locked phone, nobody there to tap) is at best "needs a workaround" (§1.2, "Needs unattended background execution"). Write no acceptance criterion that promises it runs without a tap. Name a trigger the user performs instead (stopping the alarm, the first unlock) and put the choice, with its tradeoff, in the open questions.
- Before giving a requirement "not a shortcut" because an app has no Shortcuts action, check whether the service has a web API (§1.1, Web-API extension). If it does, the verdict is "needs a workaround": name the API, the auth route (§2 C-14) and the token setup the user does once.
- The device is never asked. When a requirement works only on some devices (Health actions are iPhone only; the Action button needs iPhone 15 Pro or later), say so in its verdict and in the approval message.
- For every stored value, record where it lives and whether the shortcut can read it back (§2.2 rule 1).
- For Feishu (Lark) Bitable, read `${CLAUDE_PLUGIN_ROOT}/docs/feishu-bitable.md` and take the auth route and request shape from it.

**Output — sections 1, 2 and 3 of the spec,** filled in the template's tables.

## 4. List the assumptions to check on a device before building

Read protocol §3 Step 1. List every platform behaviour the spec relies on that nobody has seen on a real device, such as each appended entry landing on its own line or an action running while the phone is locked. These checks run before the build, not after the first real run.

**Output — section 5 of the spec:** one row per assumption: what to run on the device, and the result that proves it.

## 5. Write `specs/PRD.md` and check it

Copy `${CLAUDE_PLUGIN_ROOT}/templates/shortcut-prd-template.md` to `specs/PRD.md`, add `Status: draft — waiting for your approval` as its first line, above the template's content, and fill every section.

- Each story is a `### US-<n> <title>` heading. Each acceptance criterion is its own line starting with `**AC<m>`. Bullets, numbered lists, `- AC1:` lines and bold story lines parse to 0 criteria.
- Every story gets one acceptance criterion each for its first-run state (the target note, table, token or permission does not exist yet), its empty state (cancel, no input, nothing to show) and its error state (no network, permission denied, missing target).
- A point the user has not answered is never written as a fact. Either list it as an open question, or use a default in the spec, mark it `(unconfirmed default)` where it is used, and list it under open questions. This includes the result of a first-run, empty or error state the user did not describe, such as what cancel does, what a failed save shows or what an empty day says.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ac_coverage.py" --spec <product>/specs/PRD.md --cases /dev/null
```

Pass: it prints `covered 0/N` with N of at least 1 (the exit code equals N here, so read the printed line, not the exit code). `0 ACs parsed` means the format is wrong: fix it and run again.

## 6. Show the PRD and ask for approval

**Output 2 — the approval message:**

```
<the full text of specs/PRD.md, pasted in full even when it is long, not a placeholder or a summary>

Spec (draft): <product>/specs/PRD.md — <N> acceptance criteria parsed
Recommended by Claude Code, not said by you: <each recommendation — entry point, where values are stored, feasibility verdicts, acceptance criteria — one line each>
Needs a specific device, a workaround, or an app: <requirement → which, or "none">
Open questions (<count>), each with the default this spec uses: <each, one line: question → default>
Answer any open question you want to change, or tell me what else to change. "Approve" accepts every recommendation and every default above.
```

When the user asks for changes, edit the file, keep the draft line, run the check again and send Output 2 again. When the user approves, change the first line to `Status: approved by the user`, remove the `(unconfirmed default)` marks and section 6 rows of the defaults the approval accepted, and only then reply:

**Output 3 — after approval:**

```
Spec approved: <product>/specs/PRD.md
Next: turn these <N> acceptance criteria into test cases (the shortcut-qa skill), so every build checks them. Before the first build, the <count> device checks in section 5 run.
Start the test cases now? Reply "go" or "not now".
```

On "go", run the shortcut-qa skill on this spec. On "not now", stop.

## Checklist before you hand off

- [ ] The first message was the whole question list, each question with `My guess:` (or, when the request named no problem or task, only the one opening question)?
- [ ] Every question asked what the user needs (who, what, why), none how to build it?
- [ ] Every list item met its answered rule, or is in open questions?
- [ ] Every requirement has a verdict citing protocol §1 or §2, and no acceptance criterion promises an unattended run?
- [ ] Section 5 lists the assumptions to check on a device before the build?
- [ ] Every story has first-run, empty and error acceptance criteria?
- [ ] Every unanswered point is an open question or an `(unconfirmed default)`, none a fact?
- [ ] Every line of "Recommended by Claude Code" is in section 6, and every edge-state result the user did not give is marked `(unconfirmed default)`?
- [ ] `ac_coverage.py` printed `covered 0/N` with N of at least 1 for `specs/PRD.md`?
- [ ] The PRD was shown with `Status: draft — waiting for your approval` as its first line, the reply listed the recommendations and asked for approval, and shortcut-qa was named only after the line became `Status: approved by the user`?
