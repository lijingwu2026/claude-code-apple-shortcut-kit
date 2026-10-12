# <Shortcut name> — PRD

<!-- Save as specs/PRD.md in the product folder. Anything the user has not said goes to section 6 or is marked (unconfirmed default); it is never written as a fact. Delete these comments when done. -->

## Goal

- Who uses it: <…>
- Why: <…>
- Success looks like: <…>
- Hard constraint: <…>

## 1. Devices and entry points

| Device | OS version | How it starts (Action button, Share Sheet, Home Screen icon, automation, …) |
|---|---|---|
| <iPhone / Mac / Watch> | <…> | <…> |

## 2. Feasibility per requirement

Verdict: works / iPhone only / needs a workaround / not a shortcut (an app is needed).

| Requirement | Verdict | Protocol line it rests on | Workaround |
|---|---|---|---|
| <…> | <…> | <§…> | <name it, or —> |

## 3. Data

| Value | Stored in | Can the shortcut read it back? (protocol §2.2 rule 1) |
|---|---|---|
| <…> | <…> | <yes / no — and what that rules out> |

## 4. Stories and acceptance criteria

<!-- One `### US-<n>` heading per story. Each acceptance criterion is its own line starting with `**AC<m>`, stating a condition and what the user sees or what is stored. Every story has a first-run, an empty and an error criterion. -->

### US-<n> <story title>

**AC<m>** <condition> → <what the user sees or what is stored>
**AC<m> First run:** <the note, table, token or permission does not exist yet> → <…>
**AC<m> Empty:** <cancel, no input, nothing to show> → <…>
**AC<m> Error:** <no network, permission denied, missing target> → <…>

## 5. Assumptions to check on a device before building

| # | Assumption | What to run on the device | Result that proves it |
|---|---|---|---|
| 1 | <…> | <…> | <…> |

## 6. Open questions

| # | Question | Unconfirmed default used in this spec |
|---|---|---|
| 1 | <…> | <the default, or —> |
