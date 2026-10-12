
# ${CLAUDE_PLUGIN_ROOT}/docs/apple_shortcuts_dev_protocol.md

Apple Shortcuts (iOS Shortcuts app) platform development protocol. **Read before every build, change, or debug of a Shortcut project.**

> **Platform version anchor**: facts were gathered from the iOS 18 / iOS 26 era through iOS / macOS 27; a fact that holds only from one version on names that version. Run `sw_vers` for this machine's version. Mark any platform fact not verified by hand `[pending real-device test]`.

## Contents

- 1. Platform capability boundary — what suits / doesn't suit the Shortcut form
  - 1.1 Suits
  - 1.2 Doesn't suit (→ time for an App)
- 2. Hard-constraint list (verified, affects design)
  - 2.1 Platform hard constraints
  - 2.2 General platform design rules (distilled from the decision history)
- 3. Development flow (build-order pattern)
  - Step 0 — Design time (before starting)
  - Step 1 — Phase 0 spike (before building the plumbing, ~30min)
  - Step 2 — Per-action config table (write before building)
  - Step 3 — Build order
  - Step 4 — AI step discipline
  - Step 5 — Integration & distribution patterns
  - Appendix: action-name pitfall table
- 4. Test / verification playbook
  - 4.1 Core standard
  - 4.2 Generic app-check categories (C0-C7)
  - 4.3 Accuracy-validation pattern for AI-type shortcuts (required in Phase 0)
  - 4.4 End-to-end dogfood checklist (run after each phase is built)
- 5. Field experience / pitfalls
- 6. Shortcut → Feishu (Lark) Bitable write pattern
- 6a. Upstream reference: Apple's official user guide (`support.apple.com/zh-cn/guide/shortcuts/`)
- 7. Programmatic `.shortcut` development (platform-layer capability, reusable across products)
  - 7.1 File format: not encryption, a signature
  - 7.2 The four tools (`${CLAUDE_PLUGIN_ROOT}/scripts/`, platform-level)
  - 7.3 🔴 Check the corpus before you start — the most important item in this section
  - 7.4 Four disciplines for generating / modifying
  - 7.5 Wiring-type bugs — a high-risk category specific to Shortcuts
  - 7.6 Headless execution (Mac side)
  - 7.6a `askllm` has a cooldown — it reports a **generic error** and gets misdiagnosed as a probe bug
  - 7.6b `setvariable` doesn't accept a bare string — it must reference the previous action's `OutputUUID`
  - 7.6c The `documentpicker` path is **relative to the Shortcuts iCloud folder**, not an absolute path
  - 7.6d `documentpicker.save` **rewrites the extension** according to the content type
  - 7.6e Probe hygiene — **clean up with `probe_cleanup.py`, and don't build probes carelessly**
  - 7.7 `WFTextTokenString`: the `￼` placeholder and offsets
  - 7.8 Key schema quick reference (field names; use `--dump` to see real sample values)
    - 7.8a `WFCondition` value table (condition codes of the If test)
  - 7.9 Headless QA loop (distilled from hands-on work — reusable across products)
  - 7.10 Division of labor between human and machine — what **must** a human do, what should a machine do (measured boundaries)
    - A. Hard boundary: **four classes + two items** that only a human can do (all measured, not quoting old conclusions)
    - B. Confirmed **automatable** (stop throwing these to a human)
    - A′. iOS **content-level lineage tracking** — a class of mandatory manual work that "never shows up on the Mac"
    - C. Triage criterion (ask before starting each real-device case)
    - D. Optional levers (trade a permission for a whole class of manual work, each with a different cost)
  - 7.11 Where values come from: dig into the system framework first, then ask
- Related

---

## 1. Platform capability boundary — what suits / doesn't suit the Shortcut form

### 1.1 Suits

| Form | Description (meal-logging example) |
|---|---|
| **System-app glue flow** | Chains reads/writes across Health / Calendar / Notes / Files + arithmetic + simple interaction (take photo → AI → write Health → read back today's total → compute remaining) |
| **AI-call front end** | Apple's native "Use Model" (free) or any HTTP API (via 「URLの内容を取得」); the shortcut acts as prompt router + result parser |
| **Zero-cost MVP / demand validation** | Zero development, instant release, no review, file-as-product — a lean-validation form (e.g. a free lead-in hook + zero-cost demand-validation MVP, not the end state) |
| **Web-API extension** | A service with no Shortcuts action but a web API (Notion, Feishu (Lark) Bitable, Airtable, any REST service) is reachable through 「URLの内容を取得」 (Get Contents of URL): read, write, query. Limits: auth (§2 C-14), request shape (§2 C-15), regional blocks (§2 C-17) |
| **Low-friction trigger entry** | Back Tap (Settings → Accessibility → Touch → Back Tap → Double Tap → pick the shortcut) cuts the "open the app" friction to one action |
| **Modular buy-out product** | Run Shortcut calls each other + passes parameters + takes return values; data lives in shared system storage (Health/Calendar) → each module is a **stateless front end**, naturally interoperable |

### 1.2 Doesn't suit (→ time for an App)

| Counter-signal | Why |
|---|---|
| Needs DRM / license checks | Gating can only mean "do you hold the file"; holding it means it works, with no verification; leaks are managed by volume, not prevented |
| Complex UI / native charts / widgets / subscription IAP / auto-update | An App is a **strict superset** of a shortcut; a shortcut only has menu / confirmation card / Show Result-level interaction |
| Depends on a capability the target app has neither an action nor a web API for | No action and no API = dead end with no workaround (example: Numbers has no read action — see §2 C-2). An app with a web API is the Web-API extension row in §1.1 |
| Mass-market zero-barrier audience | Audience = people who can use Shortcuts; the form barrier is real (evidenced in the Japan market) |
| AI backend must cover all devices/regions and cannot use an external API | Apple Intelligence's three-layer gate excludes many end users (§2 C-3) |

**1.2 Additional counter-signals**:

| Counter-signal | Why |
|---|---|
| Needs a core AI engine / reproducible output / SLA | on-device `Use Model` context window **≈4K tokens** + non-deterministic output + no SLA + device/language gating → **use AI as progressive enhancement, not as the baseline**; authoritative/consistent output goes to a self-built server-side LLM |
| Needs unattended background execution | Automations are **best-effort**: delayed on lock screen/low battery; network + notification types have historically often needed unlock/tap → they don't replace server-side scheduled push; for heavy unattended work, use Pushcut Automation Server or keep it server-side |

**Full set of run entry points** (far more entry-design options than "Back Tap"): Siri phrase / Spotlight / Home Screen icon·Widget / Lock Screen Widget (no unlock needed, unless it reads protected data) / Control Center / **Action button** (15 Pro+, can be set to Choose from Menu with multiple choices) / **Back Tap** / **Share Sheet** (any app's share surface, types filterable to Text/URL/Images/Files) / NFC tag / Focus / app-open trigger / URL scheme `shortcuts://run-shortcut?name=...` / Watch.

**End-state judgment**: shortcut = lean-validation MVP; App = end state at scale. In capability, App ⊇ shortcut; the difference is the cost curve: an App needs a $99/yr developer account + real Swift development + review, while a shortcut ships with zero development. **The real lever of a self-built App = the App Intents framework** (`AppShortcut` is available out of the box to Siri/Spotlight/Action button, iOS 16+ on all models — it's the product differentiator, not making users hand-build shortcuts).

---

## 2. Hard-constraint list (verified, affects design)

> Distilled from constraints verified while building real shortcuts (technical-constraints tables, specs and verification marks). **Each item is a wall to route around at design time, not a pitfall of the implementation stage.**

### 2.1 Platform hard constraints

| # | Constraint | Why / meaning | Response |
|---|---|---|---|
| C-1 | **Log Health Sample's Type field cannot take a variable** (✅ verified) | Type is static configuration, not a runtime parameter → each HealthKit field needs its own Log action (4 nutrition fields = 4 actions) | Field count = action count; work it out at design time |
| C-2 | **Numbers has no read/sum action**; AppleScript reading is Mac-only | Write has been tested as feasible (Add Row + 辞書 mapped by column-header name) but read-back is not — **write feasible ≠ read feasible** | Never give Numbers a "must read back" duty (display-only fallback at most); accumulate with Apple Health's native sum |
| C-3 | **Apple Intelligence three-layer gate** | Chinese Apple ID / China-model CH-A device (**permanently blocked**) / needs iPhone 15 Pro/16+ — you can't control end users' devices/accounts | Dogfood on Apple-native (J/A devices can unlock by changing the account country); volume rollout must use a third-party API direct |
| C-4 | **Use Model On-Device image reading: iOS 26 ❌ / iOS 27 beta ✅** | iOS 26 On-Device can't read images (MacStories); **the iOS 27 beta's third-generation on-device model can read images** (tested: produced food recognition). PCC/ChatGPT always could | On iOS 26 vision is locked to PCC/ChatGPT; on iOS 27+ all three backends read images, but **accuracy Cloud Pro (PCC) > Cloud/On-Device** (in testing only Cloud Pro identified the ingredients correctly) → **default Cloud Pro** (most accurate + no account), On-Device only as offline/privacy fallback; cover recognition errors with a user confirmation step |
| C-5 | **Health profile age/sex can't be read** (❌ confirmed by research) | Shortcuts has no action to read birth date/sex; height/weight can be read as the latest value with Find Health Samples | Fields that can't be read → Ask for Input by hand (supports a default prefill for confirm/modify) |
| C-6 | ~~**No create-calendar action** (❌ confirmed by research)~~ → 🔴 **disproved (verified on a device; a sample is in the corpus)** | **There is a native `addnewcalendar`** (creates the calendar container) **and `addnewevent`** (creates an event; fields in §7.8). The original conclusion was wrong and caused a design detour | Use the native actions directly: the container `addnewcalendar` is created once only on first run, the event `addnewevent` creates 1 event per record (`ShowWhenRun: False` for silent) |
| C-7 | **Find Health Samples sum correctness depends on options** | If 「欠損を補填」 and 「上限」 are not turned off, the sum comes out wrong (external-source check); how the fill-missing option appears is `[pending Phase 0 test]` | Check each option for sum queries; don't run with defaults |
| C-8 | **List variable = in-memory, non-persistent** | Shortcut variables don't survive across runs | Cross-run accumulation must land in system storage (Health/Calendar/Notes) or a file (iCloud Drive) |
| C-9 | **File append = read → concatenate → overwrite-write** | Append mechanism: read existing → add a new line with Combine Text → Save File overwrite; the Overwrite switch ✅ verified to exist (「ファイルが存在する場合は上書き」) + for a fixed path set 「保存先を尋ねる」 OFF | Append flow starts at 3 actions; for frequent accumulation prefer system storage |
| C-10 | **Expenditure data depends on a peripheral** (Apple Watch) | Without a watch, Resting Energy may be unreadable | Formula fallback (example: Mifflin-St Jeor BMR used as resting) |
| C-11 | **Write-then-read ordering semantics** | Log this sample first, then Find today's total → the value read back already includes this one; no manual addition needed | Use it: fix the flow as write → read → compute |
| C-12 | **Calendar events are readable** (Find Calendar Events, ✅) | Can query the day's events | Calendar can serve as a backup accumulation/detail source |
| C-13 | **on-device `Use Model` context window ≈4K tokens** + non-deterministic output + no SLA | Long input + prompt exceeding the window errors; not suitable where reproducible/consistent output is needed | AI steps control input length; authoritative/consistent output goes to a self-built server-side LLM
| C-14 | **No built-in OAuth** (no redirect/PKCE) | Third-party OAuth flows don't work inside a shortcut | 3 workarounds: out-of-band long-lived token stored in Note/Files/Data Jar / put the OAuth exchange on your own server + shared secret / POST the token endpoint on every run and use it on the spot
| C-15 | **`Get Contents of URL` details** | Body top level must be `{}`, can't send a top-level array; timeout is not configurable in the UI (killed at ~30-60s in the background); query parameters have no UI; 4xx/5xx return a body, not an error | Build the URL by hand + URL Encode; always check Status Code; avoid putting long requests in background automations
| C-16 | **Secret-hygiene invariant** | A shareable shortcut embeds the header in plain text — distribution = leak | **Never hard-code a token**; privileged calls go through a webhook proxy, or BYO (user holds their own token, see §3 Step 5)
| C-17 | **Mainland China (GFW) availability fork** | on-device actions ✅; Apple Intelligence has a separate restricted stack in the China region `[pending real-device test]`; ChatGPT extension ❌; Notion ❌; OpenAI API ❌ | For mainland users: AI via a domestic API; the BYO data backend **can only be Bitable** (Notion is blocked)
| C-18 | **Health actions exist on iOS only** (✅ verified) | The Mac has no Health app, so Log Health Sample and Find Health Samples are missing from Shortcuts on the Mac: NL "Describe a change" on the Mac reports that no Health action exists, and a Mac run fails loudly (§7.10 B) | Build and edit Health steps on the iPhone and test them there |
| C-19 | **Find Health Samples returns samples, not a number** (✅ verified) | Arithmetic on its output gives 「計算エラー」 (number − samples). The daily total the Health app shows is the app's own aggregation and does not reach Shortcuts | Insert **Calculate Statistics (統計を計算) = Sum** and compute with its result; without Sum, Repeat over the samples and add each quantity |
| C-20 | **A Use Model response saved to a file becomes RTF** (✅ verified) | The response is rich text even with output format 辞書; Save File keeps it, so the file is `{\rtf1…}` and Get Dictionary from the file reads an empty dictionary. Wrapping the response in a Text action does not strip it | For pure JSON: have the model return only the derived values (output テキスト; 数値 gave 「モデル実行エラー」 with a multi-step prompt) → Calculate `response + 0` to force a plain number → assemble the JSON yourself in a Text action from known variables and those numbers → save that Text. Quick Look on the saved file tells RTF from JSON at a glance |
| C-21 | **Save File picks the extension by content type** (✅ verified) | Plain text → `.txt`, rich text → `.rtf`; an extension written in the subpath is ignored (the same as `documentpicker.save`, §7.6d) | Read back with the extension the file really got and delete stale copies with the other one. With Get File from Folder and folder = Shortcuts the path is `name.txt`; a `Shortcuts/` prefix doubles the folder and finds nothing |
| C-22 | **If has no numeric comparison for a text-type variable** (✅ verified) | Format Date and similar actions output text even when it looks like a number (`"04"`); If then offers only text comparators (equals / contains / begins with / ends with), and `"04"` does not begin with `"4"` | Calculate `variable + 0` turns it into a number and unlocks the numeric comparators, but nested numeric If chains still failed on a device → for range decisions use a 辞書 lookup (§2.2 rule 6) |
| C-23 | **NL "Describe a Shortcut" (iOS / iPadOS / macOS 27)** | One natural-language description builds a runnable draft of a simple shortcut; "Describe a change…" can add steps and branches to an open one when the description lists the steps | Treat the result as a draft and check every action: it hands deterministic steps to AI nodes (§3 Step 4), and complex multi-step or multi-app chains still need fixes by hand |
| C-24 | **NL "Describe a Shortcut" inside an open shortcut overwrites it** (✅ verified) | Run inside an already-open shortcut, the description rewrites that shortcut instead of creating a new one | To create a shortcut, first open a blank one (＋ New Shortcut), then describe it; say so whenever you guide someone through an NL build. Undo before closing recovers (Cmd+Z on the Mac, ↶ at the bottom left of the iOS editor) |
| C-25 | **HealthKit has no glycemic-index type** | The nutrition types cover energy / carbohydrates / protein / fat / sugar / fiber and similar; blood glucose is a different measure | Show a GI value or store it elsewhere (e.g. event notes); never write it to Health, and don't repurpose blood glucose |
| C-26 | **Scan QR/Bar Code returns only the code** | The native action reads 1D barcodes too, through the live camera aimed by hand, and returns the code value only | Product data (e.g. nutrition) needs a separate database lookup; an AI OCR step that reads the printed label needs none |
| C-27 | **Visual Intelligence can't be called from Shortcuts** | Shortcuts only has an "Open to Visual Intelligence" launcher, which returns no data | For image reading inside a shortcut use Use Model or a vision API |
| C-28 | **Append to Note depends on one existing note** | The action writes to a single note; leaving its operation unset appends to the end (✅ verified). What happens when that note is deleted, renamed, locked or shares its name with another note is `[pending real-device test]` | In a spec: an error AC for a missing target note, and a device check for a locked or duplicate-named note; create the note first when it may not exist |

### 2.2 General platform design rules (distilled from the decision history)

1. **Choose storage by "can it be read back"** (decision pattern): for each candidate storage ask "write ✅? read-back ✅?" — storage that can be written but not read can only be a pure display layer. Example split: Health = accumulation read-back source / Calendar = per-meal detail / Notes = text summary / CSV = optional export / Numbers = dropped. **Lesson: a read constraint can surface later than the write test; verify both ends when choosing.**
2. **Put data in shared system storage → the shortcut stays a stateless front end**: multiple shortcut modules reading/writing the same system data are naturally interoperable → modular SKUs (Run Shortcut gating) are feasible.
3. **Buy-out pricing → the AI backend must have zero marginal cost**: Apple-native or buyer-brings-own key; **never bundle your own API key** (one payment, API bills forever = a loss).
4. **No native update-push mechanism** → built-in version check in the shortcut: at run time fetch a version number from a URL; if outdated, prompt to download the new version.
5. **No "goto / subroutine" → the same logic must be physically duplicated** (verified in practice): Shortcuts only has If/Otherwise branches (since iOS / macOS 27, If gains an "Otherwise If", support.apple.com/en-us/149045; its plist encoding is unknown and the corpus has no sample — to use it, first build one in the GUI and export it into the corpus, §7.3), **no goto, no reusable subroutine** (`runworkflow` calling another shortcut is the only approximation, but it crosses files). So content like "Settings", which must both run on first launch and be reachable from the menu, **exists in two places** — this is a **platform constraint, not a design mistake**. Discipline: ① explicitly record which places are copies of the same logic ② **a change to one must change all** (run the acceptance AC at every place) ③ the copies may differ on purpose (e.g. "create container" lives only in the first-launch copy); write the reason for the difference.
6. **Range decisions use a 辞書 lookup, not an If numeric chain** (verified on a real device, C-22): for "which time period is it now" decisions, use the native 辞書 + N exact keys + `辞書の値を取得`; **don't use nested If + comparison operators + `+0` conversion** — the latter, rebuilt repeatedly on a real device, still read out empty, and many rounds of troubleshooting couldn't locate the break. A lookup downgrades "judgment" to "exact match", with a much smaller error surface. The more ranges, the deeper the nesting, the less reliable the If chain.
7. **Don't do illustrated onboarding inside the shortcut** → video + NotebookLM / external link carry it; inside the shortcut put only an "Open URL" action.

---

## 3. Development flow (build-order pattern)

> Distilled from a real project's stage structure. Core idea: **spike the assumptions first, then write the config tables, and only then build in the app.**

### Step 0 — Design time (before starting)

1. **Storage read-back split table**: list all candidate storage × write/read-back capability × duty (the §2.2-1 pattern)
2. **Module division**: entry menu (pick a branch on launch) + one-time setup module + high-frequency core module + on-demand modules; **first-run detection pattern** — the core module starts by reading the settings file; if unreadable → auto-jump to onboarding
3. **Permissions list**: list the system app permissions used (Health read/write/Calendar/Photos/Notes) — iOS prompts automatically on first use; no pre-authorization flow needed

### Step 1 — Phase 0 spike (before building the plumbing, ~30min)

**Purpose: validate the technical assumptions, to avoid building the whole plumbing only to find the AI is inaccurate / an action doesn't work**.

- AI accuracy (photograph real samples and check against the answers, see §4.3)
- Feasibility of key actions (a single action runs on a real device)
- Confirm the app-check list item by item (§4.2)
- **Set the exit criteria first**: pass before building; if not met → tune the prompt / change the input guidance / switch path, don't force it

### Step 2 — Per-action config table (write before building)

One table per shortcut: `# / Action (EN / Japanese) / config / verification mark`.

**Verification-mark discipline**:
- ✅ = feasibility verified with a source (web source / own test)
- ⚠️ = check in the app (option-level detail that desktop research can't resolve)
- ❌ = confirmed infeasible (→ the design must already avoid it)
- **Action names follow English**; names in non-English locales such as Japanese are first written as high-confidence translations, and only turn ✅ after a verbatim in-app check

### Step 3 — Build order

```
One-time setup shortcut (profile read/manual entry + goal calculation + save settings file)
  → core loop (input → AI → write system storage → read back → compute → display)
  → incremental features (add one by one, driven by UX feedback)
  → commercialization (volume AI-backend switch / onboarding for others / SKU split / delivery automation)
```

### Step 4 — AI step discipline

- **Write the prompt in the AI action's own prompt box (Use Model/ChatGPT)**, inserting variables (photo/confirmation text) inline — **don't use a separate 「テキスト」 action as one of several referenced inputs**; the model then tends to treat the prompt as data rather than instructions → doesn't output in the required format (tested 🐛)
- The prompt requires **JSON only** (「説明不要」) → two parsing methods: ① **set the Use Model/ChatGPT action's "output format" to 「辞書」** → the AI's JSON **is parsed directly into a Dictionary**, **skipping `Get Dictionary from Input`** (recommended: one less action, one less failure point; precondition: the model returns valid JSON) ② or `Get Dictionary from Input` to parse the text → then `辞書の値を取得` to pick the fields to write to Health (tested; output-format enumeration = 自動/テキスト/数値/日付/ブール値/リスト/辞書)
- Dogfood backend = Apple-native Use Model; volume backend = external API (via 「URLの内容を取得」) — the same prompt works with either backend
- Label estimate-type outputs 「推定値」 to manage user expectations
- **🚫 No AI nodes for data plumbing** (tested): **deterministic** processing such as JSON number extraction / dictionary value lookup / arithmetic **must not** be done with a Use Model node → use `辞書の値を取得` (Get Dictionary Value) / `Calculate Expression` (deterministic + instant + free + no drift). **NL "Describe a change" sneaks in AI nodes for these** (tested: it inserted 4 `このJSONから抽出` AI nodes → the calorie value became non-deterministic and turned into 0.04) → **after an NL build, always check and replace AI-extraction nodes with 辞書の値を取得**. Precondition: upstream Use Model output = 辞書 + clean JSON keys (no unit suffix).
  - **Detailed NL description + no-AI template** (taming NL into using deterministic actions): when asking NL to change a deterministic step, the prompt must ① name each action (「フォルダからファイルを取得」「辞書の値を取得」「統計を計算」「計算」) ② end with `【最重要】数値の取り出し・合計・引き算に AIモデルを絶対に使わない` ③ after building, still check for newly appeared Use Model nodes (NL may still ignore it).
- **🔑 The unit of an AI numeric output must be pinned by prompt instruction, not by convention**: stripping the key's unit suffix + setting Log to kcal **does not suffice** to guarantee the AI's number is kcal (convention ≠ guarantee; the AI could in theory give kJ → 4.18× wrong). The unit has three places, each with its own job: **① the prompt instruction 「数値の単位：カロリー=kcal、栄養=g」 = guarantees the output unit** (the key one) ② a clean key = stable value extraction ③ the Log action's unit = tells Health how to interpret the number, must match the instruction. The OCR-label path adds 「kJ なら ÷4.184 換算」 to cover imported goods. **A nested "unit + number physically paired" output (`{"カロリー":{"値":180,"単位":"kcal"}}`) isn't worth it in Shortcuts** (the user tested it: 「没有配对上」 [it didn't pair up]: writing Health needs a plain number so you must pull two levels, and the unit field is only useful if acted on; the kJ risk it guards against is near zero) → logical pinning suffices; no physical pairing.

### Step 5 — Integration & distribution patterns

- **Auth pattern quick reference**: static API key/Bearer (one header line) / Basic (Base64) / **token stored in Note/Files/Data Jar** (the secret stays outside the shortcut definition) / **webhook + shared secret** (most robust — the server controls the schema + the secret never enters the device)
- **Prefer Magic Variables over manual variables** (Apple's official recommendation; use Set Variable sparingly)
- **BYO-DB distribution pattern (verified consumer-grade)**: ship a "one-click copy" standard schema template (**fixed column names = the operational precondition against drift**; the video stresses not changing column names) + a video guiding self-service authorization (Bitable delegated authorization / Notion Internal token = API key) → **zero server, zero data responsibility, privacy as a selling point**. Security invariant: **the user's token always stays on the user's own device/workspace, never stored centrally**; only the OAuth "one-click Connect" experience needs a light server (storing client_secret + callback).

### Appendix: action-name pitfall table

Corrected from project evidence.

| Intent | Correct action | Error-prone wording |
|---|---|---|
| Read a file by path (no picker) | **Get File from Folder** | "Get File" |
| Get the user-selected **value** | **Choose from List** | Choose from Menu |
| **Branch** to run different actions by choice | **Choose from Menu** | — |
| Evaluate an expression | **Calculate Expression** | "Calculate" |
| Read a photo's EXIF capture time | **Get Details of Images → Date Taken** (present for both captured and uploaded photos) | — |

---

## 4. Test / verification playbook

> **This section covers method; each product's physical landing point is on the product's own side.** Acceptance matrix = that product's `specs/ac-matrix.md` (it marks which cells static checks can't reach, which must be run by the user on a real device, and the several false-green forms of the reconciliation gate); semantic invariants and destroy test = the script in that product's `scripts/` whose name contains `regression`. **"Which cases one AC should split into" is not this protocol's business** — that layer is in `${CLAUDE_PLUGIN_ROOT}/skills/shortcut-qa/SKILL.md` (axis extraction and human/machine triage) and in a separate technique library for building cases.

### 4.1 Core standard

> **Config table written ≠ verification passed**. You must actually run on a real device + check the business output: data really lands in the system app, derived arithmetic is right, trigger entry really works.

### 4.2 Generic app-check categories (C0-C7)

> Generalized from the 7 ⚠️ app-check items of a real project + research-resolved items. **Every Shortcut project, once designed, runs through this list**; list the hits in its own Phase 0.

| # | Category | What to check | Example |
|---|---|---|---|
| C0 | **Action existence** (check first; desktop research can resolve) | Does the action exist in the current iOS? Nonexistent = change the design, no workaround | Numbers read ❌ → already avoided at design time / create calendar ✅ (`addnewcalendar`, C-6) |
| C1 | **Aggregation/statistics option completeness** | Does the statistics action's operation enumeration include the one needed | Does Calculate Statistics have Sum; if not → Repeat + Calculate Expression accumulation |
| C2 | **System enum verbatim names** | Exact spelling of enums within the type picker | Health Type search "Dietary Energy" / "Total Fat" / "Body Mass" |
| C3 | **Write-behavior switch presentation** | Does the behavior switch of Save/write-type actions exist + its default | Save File's Overwrite If File Exists / turn off Ask Where |
| C4 | **Cross-locale labels** | The actual label of the same field/action in the target language locale | 「撮影日」 vs 「作成日」; Japanese action names verbatim |
| C5 | **Hidden correctness impact of query options** | The impact of query-action options on the result's **value** | Find Health Samples' fill-missing affects sum correctness |
| C6 | **AI backend availability on this device** | Device/region/account gating + modality capability (can it read images) | ChatGPT vs PCC choice; trial-run once within the setup module, give a fix hint on failure |
| C7 | **Parameter variable-ability** | Which parameters accept variables, which can only be static | Log Health Sample's Type can't be a variable → action count doubles |

**Research layering discipline**: desktop research can resolve **existence-type** questions (C0); **option-level details** (C1-C5) are often missing or outdated in web sources → mark ⚠️ and leave them to a real-device app-check; don't draw hard conclusions at the desktop layer.

### 4.3 Accuracy-validation pattern for AI-type shortcuts (required in Phase 0)

| Mode | How to verify | Pass criterion |
|---|---|---|
| **Exact reading** (OCR label type) | Photograph 3-5 real samples → AI reads → compare with the printed values | Numbers read correctly character by character |
| **Estimation** (open recognition type) | 5 real samples from the target domain → AI estimates → compare with a reference | Error tolerance **set in advance** (e.g. ±25%) |

Exit if not met: tune the prompt (stress the weak points / label the output 「推定」) or change the input guidance (e.g. guide the user to photograph the label rather than the real item) — **don't leave accuracy problems to the plumbing stage**.

### 4.4 End-to-end dogfood checklist (run after each phase is built)

- [ ] Data really lands in the system app (visible by eye inside the target app, not self-reported by Show Result inside the shortcut)
- [ ] Derived arithmetic is right (values correct along the read-back → compute → display chain)
- [ ] Trigger entry really works (Back Tap / each menu branch)
- [ ] The first-run detection pattern works (no settings file → the core module auto-jumps to onboarding)
- [ ] Note UX improvement points → feed them to the next phase

---

## 5. Field experience / pitfalls

Platform facts from project field logs are in §2.1; each project keeps its own log.

---

## 6. Shortcut → Feishu (Lark) Bitable write pattern

Read `${CLAUDE_PLUGIN_ROOT}/docs/feishu-bitable.md`.

---

## 6a. Upstream reference: Apple's official user guide (`support.apple.com/zh-cn/guide/shortcuts/`)

**What it can answer**: how an action works conceptually — variables / list operations / Choose from Menu / If / Repeat / Find and Filter /
Show Alert / action-extension input types / URL schemes / web APIs / date and time formats — exactly the territory of this protocol's §1-§6
(the guide's whole 「高级捷径」 [Advanced Shortcuts] section).

**What it can't answer**: action identifier strings (e.g. `is.workflow.actions.conditional`) · parameter key names
and values (e.g. `WFCondition=4`) · the `.shortcut` AEA1 container structure · the `￼` offsets of `WFTextTokenString`
(the territory of §7). The guide is written for people tapping the screen with a finger — to look up an action's description, its answer is 「轻点操作的图标，
然后轻点『显示简介』」 [tap the action's icon, then tap "Show Info"]: the description is in the App, not on the web.

**Named pointer**: the page 「处理时间戳（UNIX 时间）」 [Handle timestamps (UNIX time)]
(`support.apple.com/zh-cn/guide/shortcuts/apdfb33b0e17/ios`) names, verbatim, the three actions 「日期」 [Date],
「调整日期」 [Adjust Date], 「格式化日期」 [Format Date] as able to do UNIX time conversion. **But it covers only seconds, not milliseconds** (the page defines UNIX time
as a number of seconds), **and only the reverse direction** (UNIX time → readable date, not readable date → epoch milliseconds) — when citing this
pointer you must carry these two qualifiers, otherwise it misleads (a millisecond chain once had to be cloned from another shortcut,
not read from this page, see `${CLAUDE_PLUGIN_ROOT}/docs/feishu-bitable.md`, "A `datetime` field accepts only epoch milliseconds").


---

## 7. Programmatic `.shortcut` development (platform-layer capability, reusable across products)

> **In one sentence**: a `.shortcut` can be **read, modified, generated, and signed**, entirely without external keys; plus four tools, one
> discipline (check the corpus before you start) and one class of Shortcuts-specific high-risk bug (wiring-type, invisible to the eye).
> **For any later programmatic Shortcut development, start from this section; don't re-explore.**

### 7.1 File format: not encryption, a signature

The file header `AEA1` (Apple Encrypted Archive) is easily misjudged as "encrypted, can't be opened". But the profile field = **0**
= `hkdf_sha256_hmac__none__ecdsa_p256` — the middle `none` is the **encryption-algorithm slot**. The payload only has an
ECDSA-P256 **signature**, no encryption. `aea decrypt` reporting `-sign-pub is required` is not asking for a decryption key;
it is asking for the **signature-verification public key**, and that public key sits in the file's own auth data (the `SigningCertificateChain`
bplist → the leaf cert's SubjectPublicKeyInfo).

```
Read:  .shortcut → [take the leaf cert public key PEM] → aea decrypt → AA01(Apple Archive)
             → yaa extract → Shortcut.wflow(binary plist) → plistlib
Write: dict → plistlib FMT_BINARY → Shortcut.wflow
        → /usr/bin/shortcuts sign -m anyone → .shortcut
```

**The write path doesn't need an Apple private key**, but the two signing modes differ (`man shortcuts`): `-m anyone` "will notarize
via iCloud, and allow anyone to import" — it goes through iCloud notarization, so it is not purely local; `-m people-who-know-me`
"will sign locally", but only your own devices, or people who have your contact info in their contacts, can import. The tools are all built into macOS:
`aea` / `yaa` / `shortcuts` / `openssl`.

**Four format pitfalls (all hit in testing)**:

| Pitfall | Truth |
|---|---|
| `aea` only accepts a **PEM** public key | DER and a raw x9.63 (65B) key both give `Error parsing public key file` |
| What decrypt outputs is not a plist but an `AA01` **Apple Archive** | `plutil` reports `Unexpected character A`; there is another `yaa extract` layer in between, containing `Shortcut.wflow` |
| `strings` not finding an action identifier **≠ the content is encrypted** | The payload is lzfse-compressed, and compression alone makes `strings` miss everything. Don't take "can't grep it" as evidence of "can't decode it" |
| **The system Gallery has bare `.wflow` files** | `/System/Library/PrivateFrameworks/WorkflowKit.framework/Resources/Gallery.bundle/Contents/Resources/*.wflow` (`ls` it piped to `wc -l` for the count) — unsigned and unencrypted, `plistlib.loads` works directly (the official samples = a free corpus) |

### 7.2 The four tools (`${CLAUDE_PLUGIN_ROOT}/scripts/`, platform-level)

| Tool | What it does |
|---|---|
| `shortcut_io.py` | Read/write library + CLI. `open_shortcut()` / `save_shortcut()`; `--tree` prints the structure indented by control flow · `--prompts` dumps only the AI prompts |
| `audit_wiring.py` | **Static wiring audit C1–C6** (see §7.5). `--selftest` verifies a positive case with a file known to contain a bug + verifies zero false positives on a negative case |
| `shortcut_action_index.py` | **Corpus index** (see §7.3). `--check <action>...` answers yes/no (`✅ N sample(s)` / `❌ no samples`; exit code = how many are missing) · `--dump <action>` prints the complete parameter schema of a real sample · `--toolkit <action>` prints Apple's catalog entry for the action: its legal setting keys and enum values, not a sample (§7.3) |
| `shortcut_build.py` | **Patch-script helpers + write gate**. Helpers: `uid` / `var` / `out` / `attach` / `tok` (§7.7) / `setvar` / `locate`; `write()` = temp file → audit_wiring → the product's ac_coverage → the product's regression script → the corpus gate for new actions → `os.replace` (§7.9 ⑦a), and after passing the gates, delivery (§7.6). Which QA gates run is the project's `.shortcut-dev.json` choice (`builtin` / `own` / `none`, written by `doctor.py --setup`; no file = no build). The gate order and INFO lines are in its `--help` |

Product-specific scripts (generating variants / patching / running eval) live in each product's own `scripts/` and import the four above; new patch scripts use `shortcut_build`'s helpers and write to disk only via `write()` (the `tok()` / `_gate()` copies carried in each product's old scripts have not been migrated).

Read `man shortcuts` and `shortcuts help <subcommand>` for the CLI (run, list, view, sign — there is no import or delete command).

### 7.3 🔴 Check the corpus before you start — the most important item in this section

> 🔴 **The corpus counts the file you just generated**. `shortcut_action_index.py --check`
> scans the project + iCloud + Gallery, and **the `.shortcut` you wrote this round immediately becomes "corpus"**.
> Tested: `filter.health.quantity` reported 33 samples one day and 35 the next — the extra 2 were the v18 committed by this very round.
> → **When reporting "N samples", state the measurement time point**; when judging "is there precedent for this action", look at the
> **count that existed before you started** in the `--check` output, not the total. `--check` has gained three-level annotations (all from within 24h = 🔴 equals no corpus).


**Hand-writing the parameter schema of an action you have never seen fails silently**: Shortcuts doesn't validate parameters, and `shortcuts sign` also
signs it as is (tested: it only changes the top-level `WFWorkflowClientVersion` and keeps the action layer byte for byte → **signs fine ≠ parameters right**), and the breakage only shows up when it runs on a real device. So the discipline is to **use only action types that have byte-for-byte real samples in the corpus**.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/shortcut_action_index.py" --check addnewevent exit dictionary
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/shortcut_action_index.py" --dump addnewevent   # see the real field names
```

**The corpus = the segments of `corpus()` in `shortcut_action_index.py`** (its docstring table lists them): all `.shortcut` files under the
current directory (run from the project root; `archive/` and dot-dirs excluded) + the plugin's bundled `examples/` (when run from the plugin; it includes `action-library/`, one neutralized `.wflow` sample per action type) + the `.shortcut` files at the root of iCloud Drive and of the Shortcuts
app's iCloud Documents folder + the system Gallery's `.wflow` files + the `.wflow` files under `~/Library/Application Support/apple-shortcut-kit/action-library/` (`local`: the user's own library built by `build_action_library.py --sbench`; optional) + any directories in `SHORTCUT_CORPUS`. **Don't copy the file count or the type count into this document** —
run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/shortcut_action_index.py" | grep -E '^corpus =|types in total'`; it prints
`corpus = N files` and `N action types in total`.

⚠️ **What it can't scan**: shortcuts that are installed but were never exported (`~/Library/Shortcuts/` and Group Containers are
blocked by TCC; `ls` directly gives `Operation not permitted`; to read them the terminal needs Full Disk Access). `shortcuts list`
only shows names and gives no content → to bring one into the corpus, export it to a file first.

🔴 **Zero corpus hits ≠ the action doesn't exist**: the system's own `WorkflowKit.framework/Resources/Localizable.loctable`
has one `(Action Name)` entry per action, one set per language (both counts change with the OS version;
`python3 -c "import plistlib,pathlib;t=plistlib.loads(pathlib.Path('/System/Library/PrivateFrameworks/WorkflowKit.framework/Resources/Localizable.loctable').read_bytes());print(sum(1 for k in t['en'] if k.endswith('(Action Name)')), len(t))"`
prints the entry count, then the language count),
while the identifiers covered by this machine's corpus are only a small part of them (**don't copy the current number into this document**: run the `shortcut_action_index.py` command above and read
the `N action types in total` line; ⚠️ the basis is all the segments above, **a good deal larger than "how many types are in the project directory"** — comparing the count taken from the project directory
alone against the loctable count subtracts two different bases).
A gap that `--check` / `--dump` can't answer **does not mean the action doesn't exist**; it only means **nobody has exported a shortcut containing it**.
The right move is one of two routes; either way the value enters the corpus:
- **Build-and-verify** — when the action runs on a Mac and its effect can be read back: build a `probe-*` shortcut with the best-guess value, deliver and run it headlessly (§7.6, probe hygiene §7.6e, loop §7.9), and accept the value only when the actual effect matches — exit 0 proves nothing, a wrong value usually falls back to a default silently. Keep the probe file in the project directory as the sample.
- **Export** — use it once in the GUI and export. Required when the action cannot run on a Mac (Health writes, camera, iPhone-only) or its effect cannot be read back.

**Apple's action catalog (`shortcut_action_index.py --toolkit <action>`)** answers which setting keys a first-party action has and which enum values are legal, so it narrows the best guess for build-and-verify. It does not show working usage or how steps connect, and it never counts as a sample: a value taken from it still goes through one of the two routes above. It is a macOS 27 / iOS 27 snapshot of Apple's ToolKit database, extracted by Federico Viticci (MIT). Known gaps: control flow (If, Menu, Repeat) is absent; `is.workflow.actions.list` lists 0 parameters though real files use `WFItems`; some covered actions use keys it doesn't list, so a key missing from it is not proof the key is illegal. This Mac's own live ToolKit database (`~/Library/Shortcuts/ToolKit/`) would match the installed OS, but reading it needs Full Disk Access, so it is not read.

**Probe-verified defaults** — leaving one of these settings out of the action gives the default shown. Add a row only from a probe whose effect was read back.

| Action | Setting left out | Result | Evidence |
|---|---|---|---|
| Append to Note (`is.workflow.actions.appendnote`) | `operation` | appends to the end of the note | probe on macOS 27.2 |

The library's `appendnote` sample has `operation=prepend`; copying it as-is prepends.

> **Why this is written as the manual's number-one discipline** (the record of answering wrongly twice in a row, kept, not deleted):
> The first time I said "6 action templates are missing, please have the user hand-build a harness shortcut for me" — in fact 3 of them were right in
> **the same repo** (a bookkeeping shortcut and a timer shortcut), and I hadn't looked at all.
> The second time, after the correction, I said "only `addnewevent`
> remains as a hard gap, I'd have to guess the schema and then test" — one sentence from the user, telling me to consult a time-tracker shortcut by name, filled in all of them.
> **Both answers were already sitting on the user's hard drive; the cost was two pointless round trips and nearly making the user hand-build it.**

### 7.4 Four disciplines for generating / modifying

> 🔴 **Fifth item**: **gate checks first, import dialog after**.
> Popping the dialog with `open -a Shortcuts` first and running the regression gate after = making the user tap something not yet verified.
> → Write the gate into the generator: if `_gate()` fails it raises `SystemExit`, so **the official file is never even written**,
> and naturally there is nothing to import. (All of the nutrition-log example's `fix_v*.py` already have this shape.)

1. **Use only action types that have samples** (§7.3). No sample → first extend the corpus (export a shortcut that contains it),
   instead of guessing.
2. **Copy whole blocks > assemble by hand**: when you need an action, `copy.deepcopy` an existing sample and change only the necessary fields
   (UUID / bound variable name / concrete values). AI prompt types in particular (`WFLLMPrompt`) must be copied byte for byte —
   rewriting the prompt means you are no longer testing the production path.
3. **Locate without hard-coded indices**: use a semantic reverse lookup ("who appends to variable X" / "whose sample type is Y")
   + `assert` a unique hit. If someone edits the file the indices drift, and hard-coding is certain to misalign.
4. **After every change, run `audit_wiring.py`**, and assert "the target problem is gone + no new type of problem was introduced".

### 7.5 Wiring-type bugs — a high-risk category specific to Shortcuts

> **Two high-frequency forms**:
> - **C7 the same helper used in two different positions**: the **wrapped** form of `out_ref()` is correct for a **parameter slot**
>   and wrong **inside `attachmentsByRange`** (which needs a **bare ref**) → on a real device it shows 「不明な変数」.
>   When writing a helper, put "which position it is used in" into the function name or an assertion; don't let one helper span two serialization contracts.
> - **C20 changing only the consumer layer, not the producer layer**: a key + rules + fallback were added to the JSON step, but the **upstream data-fetch step was not changed by a single word**
>   → the consumer-side prompt **looks completely normal on its own**, every static check says OK, and the gap is that upstream never put that item into the pipeline at all.
>   **The question to ask: from which step does this field's value begin to exist? Did that step change?**
>   The machine assertion already landed = `I8-4` (透過のみの路は上流で全項目を取得) [the pass-through-only path fetches every item upstream].


Shortcuts data flow is **UUID-bound** ("use the output of the Nth action"), while the UI shows it only as a colored chip.
So a class of bug appears that is **invisible to the eye and that a real-device single-path test can't find**:

> **Bound to the output of another, mutually exclusive branch** → that branch didn't run → the value is empty → **silently writes 0 / writes empty, no error**.

A real case (AI Diet Log): all 4 Health fields' values were bound to the AI output in the 「🏷️ラベル」 branch;
when 「🍽️食物」 (the main path) was chosen, that action never ran → **all 4 fields were written empty**. The product's earlier acceptance was 3
ad-hoc probes, and the probes happened to take the ラベル path, so they were green.

The 6 checks of `audit_wiring.py` (C1–C6 are its own numbering; they do not correspond to any other C-numbered list):

| Item | What it checks |
|---|---|
| **C1** | Dangling reference (the referenced UUID doesn't exist in the file) |
| **C2** | Duplicate UUID (it is uncertain which one a binding points to) |
| **C3** | Dead-write variable (written but read by no one in the whole file → computed then thrown away, or the downstream isn't built yet) |
| **C4** | **Cross-branch reference** ← the kind described above. Criterion = **the referenced side's branch path must be a prefix of the referencing side's** |
| **C5** | Health key chain: reconcile `health.quantity.log`'s sample type → unit + the key it reads via `getvalueforkey` must appear literally as `"<key>"` in the prompt of some askllm before it (if the file has no askllm → the key part is skipped with one INFO line, the unit is still checked) |
| **C6** | Placeholder offset: every `{offset, 1}` of each `attachmentsByRange` must point at a `￼`, offsets counted in UTF-16 code units (§7.7) |

> **Lesson from deriving the C4 criterion**: the first version was written as "both are inside a block and the branch numbers differ" → it **missed the most common form**
> (the referencing side is **outside** the block, the referenced side is **inside** some branch). Only the selftest positive case FAILing forced the correct criterion.
> **A newly written detector must validate itself both ways, with a "positive case of known answer + a negative case known to be 0"**, otherwise it only looks like it works.

### 7.6 Headless execution (Mac side)

- `shortcuts run <name> --input-path <f> --output-path <o>` — **can run already-imported shortcuts headlessly in batches**. Combined with the "fixed file entry" pattern (reading `~/Library/Mobile Documents/iCloud~is~workflow~my~workflows/Documents/<fixed name>`),
  you can feed inputs and read outputs from a Bash loop, with zero clicks.
- ⚠️ **When the entry file name hard-codes an extension, convert the format for real**: iPhone photos are **HEIC**, and if the entry is named `x.jpg` →
  a plain `cp` = a name that says jpg with HEIC content, and Shortcuts, judging the type by extension, may read a corrupt image. Use `sips -s
  format jpeg` (built into macOS) to really convert; files that already are JPEG are simply cp'd without re-encoding.
- ❌ **The `shortcuts` CLI has no import / export** (only `run` / `list` / `view` / `sign`) →
  **every "change, then test" round needs one manual import click**. So **batch up** uncertain changes and give them to the user for import in one go, not one at a time.
  🔴 **Once enough have piled up and it is time to import, delivery is my job, not making the user go digging through the project folders** (forced out by the user's single sentence
  「你不发起，我怎么添加？」 [If you don't initiate it, how am I supposed to add it?]). Either route works, and **which one to use must not depend on guessing where the user is** —
  `open -a Shortcuts <file>` pops the "Add" dialog on the user's Mac; `SendUserFile` pushes the file to the device the user is using.
  **The Mac route is already built into the code**: after `shortcut_build.write()` (and its CLI) passes the gates and writes to disk, it runs `open -a Shortcuts` itself
  and prints the plist md5 + the `feature=` line (the version feature) — it pops the dialog only on interactive runs (`CLAUDE_CODE_ENTRYPOINT=cli`,
  or that variable absent and a TTY present; with `SHORTCUT_NO_OPEN=1` / headless it only prints the command, see its `--help`).
  On both routes, put **this version's plist md5** and **a visually recognizable version feature** in the caption / note
  (e.g. what the entry line looks like), otherwise after installing the user can't tell which version was installed.
  🔴 **The real failure form is not "chose the wrong route", it is "walked neither"** (verified): once I shipped a build and said
  "batch it, don't import now"; two days later I said "the file is in iCloud, go and tap it" — `open` was never run once,
  so of course the user never saw that dialog. **Deliver as soon as the build is out; don't stop at the "build shipped" state.**
  🔴 **Check, deliver, confirm — never relay manual import steps**: before asking the user to import, check that the file exists. After the user presses Add, confirm it yourself with `shortcuts list` — the user's reply is not needed. If the user asks how to import, or can't find the dialog, the agent re-runs `open -a Shortcuts <file>` itself and never gives the user manual import steps. (Observed once: a probe file vanished from the scratchpad about 1 minute after the dialog opened, cause unknown, and the agent kept asking the user to press Add.)
  🔴 **An update to a name already in `shortcuts list` deletes the old copy first, then imports**: importing beside it adds a second shortcut with the same name and a new identifier, and `shortcuts run <name>` then fails to find it (measured on macOS 27.2). So on an interactive run `write()` runs the helper `kit-replace-old` (`replace_old.py`; built on first use, one Add) — one 削除 — waits until the name is gone from `shortcuts list`, and only then opens the import (one Add). キャンセル or no answer within 3 min → nothing is imported; it stops with the command to retry.
- ❌ macOS **has no Health app** (neither `/System/Applications` nor `/Applications` has one; HealthKit.framework
  exists but that is Catalyst support) → e2e involving Health writes/read-backs **can only be verified on the iPhone**.

### 7.6a `askllm` has a cooldown — it reports a **generic error** and gets misdiagnosed as a probe bug

**Symptom**: `shortcuts run` returns

```
Error: モデルの実行中にエラーが起きました。
```

**There is no information at all** to tell "my shortcut is wrong" from "the model is unavailable right now".

**One layer Apple officially states** (support.apple.com/en-us/149045, iOS / macOS 27): Apple Intelligence features that depend on a server-side model
"are subject to daily usage limits, including but not limited to … AFM 3 Cloud
models in Shortcuts", and the quota "may vary by feature, request complexity, system demand". So besides the short-term cooldown measured below,
there is also a **per-day** cap — consider it when the control also fails and waiting 10 minutes doesn't recover it.

**Measured**: the same probe ran 3 times in a row all green 20 minutes earlier; after 5+ more `askllm` runs in a short time,
**it started reporting this error itself**. During the cooldown, **every** shortcut that contains askllm fails.

🔴 **Diagnostic discipline (the same nature as the §7.9 "destroy test's own premise")**:
when an askllm probe reports an error, **step one is not to examine the one you just built**, but to **run a known-good askllm probe as a control**:

```bash
shortcuts run "<the last askllm probe that passed>" --output-path /tmp/ctl.txt
```

- The control **also fails** → the model layer, unrelated to your change; wait 5-10 minutes and retry
- The control **succeeds** → only then is it a problem with the one you just built; investigate further

**The cost of skipping this step is on record**: a symptom of the same family (v24 won't open) was once investigated at the file layer for 6 hours with 6 wrong hypotheses,
and the real cause was system state, fixed by a reboot.

**How to run in batches**: when a batch of probes must run several times, **don't fire them back to back** — look at the results after each round,
and if a rerun is needed leave a few minutes in between; or write a background retry loop (exponential backoff 5min / 7min / 10min).

### 7.6b `setvariable` doesn't accept a bare string — it must reference the previous action's `OutputUUID`

**Symptom**: after assigning a value to a variable in a probe and running it, the LLM replies 「数値が入力されていません」; the variable looks set, but is actually empty. **No error**.

**Cause**: the `WFInput` of `is.workflow.actions.setvariable` **only recognizes an action-output reference**:

```python
# ❌ silently ineffective — the variable is empty
{"WFVariableName": "身長",
 "WFInput": {"Value": {"string": "160"}, "WFSerializationType": "WFTextTokenString"}}

# ✅ the only way that works — produce with gettext first, then reference its UUID
u = str(uuid.uuid4()).upper()
gettext("160", uid=u)                      # WFWorkflowActionParameters["UUID"] = u
{"WFVariableName": "身長",
 "WFInput": {"Value": {"OutputUUID": u, "Type": "ActionOutput", "OutputName": "テキスト"},
             "WFSerializationType": "WFTextTokenAttachment"}}
```

**Write-time assertion** (copy as is; the same nature as the offset assertion in §7.7 — both are "a silent failure must become an error at write time"):

```python
seen = set()
for a in acts:
    p = a["WFWorkflowActionParameters"]
    if u := p.get("UUID"): seen.add(u)
    if a["WFWorkflowActionIdentifier"].endswith("setvariable"):
        w = p["WFInput"]["Value"]
        assert w.get("Type") == "ActionOutput", f"{p['WFVariableName']} used a bare string"
        assert w["OutputUUID"] in seen,         f"{p['WFVariableName']} points to a nonexistent UUID"
```

**One more thing**: `shortcuts run` **returns only the output of the last action**. A probe that must verify several things → first `setvariable` each result, then use one `gettext` at the end to collect them into a single output (compute the placeholders' offsets per §7.7, don't hand-write them).

> 🔴 **This one was stepped on because "a working recipe already existed but wasn't reused"**: earlier the same day `probe-hitokoto-over2` used exactly gettext+OutputUUID and ran fine; for the next probe I didn't read how it was written, and re-composed a bare-string version from memory → silent empty value. **Before building a new probe, `open_shortcut()` and look at the first 3 actions of the last working probe** — faster than re-deriving, and it won't flip over. Same family: §7.7 "offsets are always computed, never hand-written", §7.3 "check the corpus before you start".

### 7.6c The `documentpicker` path is **relative to the Shortcuts iCloud folder**, not an absolute path

The `WFGetFilePath` of `documentpicker.open` and the `WFFileDestinationPath` of `documentpicker.save`
are both relative to

```
~/Library/Mobile Documents/iCloud~is~workflow~my~workflows/Documents/
```

**Passing a filesystem absolute path gives `ファイル"X"は存在しないため、開けませんでした` right away** (tested:
passing `/Users/<you>/Downloads/IMG_7534.PNG` → reports it doesn't exist, while the file is really there).

- The nutrition-log example's `diet_profile.txt` uses exactly this convention (`"/diet_profile.txt"` → in the directory above).
- **When a probe must read material from the project folder/Downloads** → **`cp` the material into the root of that directory and use a simple relative path**
  (`/a10_probe.png`). iCloud syncs it to the iPhone, so **the probe can run on both platforms**.

🔴 **The anti-pattern (I used it once, don't copy it)**: "the probe is already built and I don't want to re-import → **create the matching nested path** under that directory
for the string it looks for" (it was passed `/Users/<you>/Downloads/X.png`, so I ran `mkdir -p .../Documents/Users/<you>/Downloads/`).
**It buys saving one import click, at the cost of making the probe Mac-only** — that nested directory exists only on the machine where I created it,
and the iPhone can't resolve the path (the user's test: 「图片路径无法识别」 [the image path isn't recognized]).

**And the criterion of that experiment was valid only on the iPhone** — the one click saved by the trick cost the whole experiment its executability.
**Discriminator**: for a trick that saves manual work, first ask "will it pin the artifact to this machine?". Material paths, absolute paths,
and directory structures created locally — once any of these three enters a probe, it is useless across devices.

### 7.6d `documentpicker.save` **rewrites the extension** according to the content type

Writing `"/a10_launder.txt"` lands **`a10_launder.rtf`** — the output of `askllm` is rich text, and
`documentpicker.save` decides the extension by content type itself, **ignoring what is in `WFFileDestinationPath`**.

The consequence is not an error at the write step, but a **downstream `.open` that can't find the file**:
`ファイル"a10_launder.txt"は存在しないため、開けませんでした` — it looks like the save failed,
when in fact the save succeeded and the name is not the one you wrote.

**Discriminator**: when "file doesn't exist" is reported, first run `find <Shortcuts Documents directory> -name "<basename>*"`
(**without the extension**) to see what it actually landed as.

> The two halves of the same debugging session as §7.6c: first the path base was wrong (absolute vs relative), and after fixing that the extension rewrite hit.
> Both belong to "the write succeeded but downstream can't find it", with the error text exactly the same.

### 7.6e Probe hygiene — **clean up with `probe_cleanup.py`, and don't build probes carelessly**

**Platform facts (verified; Delete Shortcuts on macOS 27.2)**:
- The `shortcuts` CLI only has `run` / `list` / `view` / `sign`, **no delete**
- AppleScript **only implements `run`** (the only `<command name=` in `Shortcuts Events.app/Contents/Resources/Shortcuts.sdef` is run)
  → trying `delete shortcut "X"` is a **silent no-op**: no error, and no deletion
- `~/Library/Group Containers/group.com.apple.shortcuts` is **sandbox-protected and unreadable**, no DB path
- Apple's in-shortcut action **Delete Shortcuts** (`com.apple.shortcuts.DeleteWorkflowAction`) **can delete**, with one confirmation per run: the dialog lists the targets and has only キャンセル / 削除 (no always-allow)

→ After a probe's effect is checked, run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/probe_cleanup.py"`. It deletes every shortcut whose name starts with `probe-` through its helper shortcut `kit-cleanup-probes` (built on first use; one Add), then verifies the `probe-` count is 0 and the other shortcuts are unchanged. Each run needs one 削除 click; exit codes are in its `--help`.

**Two disciplines**:

1. **Before building a probe, ask "is it the same shape as production?"** — especially the **type of the data source**.
   🔴 Evidence: the A10 experiment built **6 generations** of probes in a row (v1 missing the date → v2 → v3 extension → v4 no overwrite →
   v5 local path → v6), each generation fixing the surface symptom of the previous one, while **the real defect was there from v1**:
   production uses `takephoto`/`selectphoto` (**photo-library items**), and my probe used `documentpicker.open` (**file items**),
   so the **lineage source types are fundamentally different** → that A/B tested the wrong thing from start to finish.
   The conclusion "the Mac doesn't reproduce the symptom" is also a product of this — the probe had no photo to trace at all.
   **What to ask when one run fails is "is the shape right?", not "which parameter did I write wrong?".**
2. **Name every probe `probe-*`** — the `probe-` prefix is what `probe_cleanup.py` matches; a probe with any other name (e.g. `label-*`) is not cleaned up.
   One QA campaign leaves 20+ in the library (25 measured, of which 11 were 6 generations of the same experiment).

### 7.7 `WFTextTokenString`: the `￼` placeholder and offsets

> 🔴 **Offsets are always computed, never hand-written** (hit more than once).
> Hand-written offsets such as `{22, 1}` / `{39, 1}` are **bound to be wrong** (CJK / emoji / newlines all shift positions),
> and the consequence of a wrong one is that **the variable silently renders empty** — no error, no red, the run just comes out blank.
> → Always use `shortcut_build.tok(template, refs)` for new code (`{{key}}` → `￼`, offsets recorded in **UTF-16 code units**).
> The old `tok()` / `token_string()` in each product's `scripts/` record `len(s)` / `str.index` (Python code points),
> so they misalign as soon as an emoji appears before a `￼`. **After writing, read back and assert that every offset points at a `￼`** — `audit_wiring.py` C6 checks exactly this
> (`shortcut_build.write()` always runs it before writing to disk); a hand-written assertion must take UTF-16 units:
> ```python
> u = s.encode("utf-16-le")
> for k in att:
>     o = int(k.strip("{}").split(",")[0])
>     assert u[2*o:2*o+2] == "￼".encode("utf-16-le")
> ```
> Recurrence measured: hand-written offsets when building a two-arm probe → both arms' outputs were entirely empty, which was briefly misjudged as "the mechanism failed".


The `￼` (U+FFFC) in an AI prompt / text is a **variable placeholder**. The binding is in `attachmentsByRange`, whose key has the form
`{offset, length}`: **offset = the 0-based UTF-16 code unit index of the `￼` in the string (NSRange), length is always 1**.
It differs from the Python character index only when a non-BMP character (emoji etc.) precedes the `￼`: of the 28 such offsets in the corpus, all match
only under UTF-16, and counting by code point misses 28/28 (measured; `audit_wiring.py` docstring C6).

🔴 **The consequence of an out-of-range offset is not reading an empty value, it is Shortcuts crashing at the moment of import** — so the read-back assertion above is crash prevention, not error prevention.
Source: the third-party `viticci/shortcuts-playground-plugin`'s `SKILL.md` Key Rules #6/#7 (**third-party, hand-maintained, not Apple's original text**).
We ourselves have only measured the half "wrong offset → silently renders empty"; we have not hit the out-of-range half on a real device — the two are listed side by side, don't treat it as something we verified.

```python
{'WFSerializationType': 'WFTextTokenString',
 'Value': {'string': 'この￼写っている…', 'attachmentsByRange': {'{28, 1}': {'Type': 'Variable', 'VariableName': '画像'}}}}
```

**When editing the prompt text, if you add or delete characters across a placeholder position, you must update these offsets in step**, otherwise the variable binds to the wrong position. The safe way
= template compilation (`{{名前}}` → `￼` + automatic offset computation), and **refute the algorithm with a real action** (what it builds
must be byte-for-byte identical to the original) — for new code use `tok()` of `${CLAUDE_PLUGIN_ROOT}/scripts/shortcut_build.py`; the old precedent,
the `token_string()` + `_selftest()` of the nutrition-log example's variant builder,
counts by code point and holds only for strings with no emoji before the `￼`.

### 7.8 Key schema quick reference (field names; use `--dump` to see real sample values)

| action | Key fields |
|---|---|
| `addnewevent` | `WFCalendarItemTitle` · `WFCalendarItemStartDate` · `WFCalendarItemEndDate` · `WFCalendarItemNotes` · `WFCalendarDescriptor` (which calendar) · `WFAlertTime`/`WFAlertCustomTime` · **`ShowWhenRun: False`** (= 作成シートを表示 OFF, silent creation) |
| `health.quantity.log` | `WFQuantitySampleType` (`Dietary Calories`/`Carbohydrates`/`Protein`/`Total Fat`) · `WFQuantitySampleQuantity` (`WFQuantityFieldValue` containing `Magnitude` + `Unit`) · `WFQuantitySampleDate` |
| `filter.health.quantity` | `WFHKSampleFilteringUnit` · `WFContentItemFilter` (`WFContentPredicateTableTemplate`, `Property: Type` + `Property: Start Date`) |
| `documentpicker.open` / `.save` | `WFFile.fileLocation` (copy the whole block, don't hand-write) · `WFGetFilePath` / `WFFileDestinationPath` · `WFFileErrorIfNotFound` / `WFSaveFileOverwrite` / `WFAskWhereToSave` |
| Variable reference | `{'WFSerializationType':'WFTextTokenAttachment','Value':{'Type':'Variable','VariableName':...}}` |
| Action output reference | Same as above but `{'Type':'ActionOutput','OutputUUID':...,'OutputName':...}` |
| Control flow | `WFControlFlowMode` 0=block start / 1=next branch / 2=block end (**integer, not string**); `GroupingIdentifier` pairs up the same block. ⚠️ A third party says mode 2 "carries only the two keys `GroupingIdentifier` + `WFControlFlowMode`" — **in one measurement, 98 of our 131 mode-2 actions also carried `UUID`**, so a validator written to that sentence would have falsely flagged 98 artifacts |
| `text.match` | `WFMatchTextPattern` (ICU regex) · `text` (`WFTextTokenString` + `attachmentsByRange`). **The default Japanese `OutputName` of the output = `一致`** (verified by action `[7]` of the bookkeeping shortcut — the first version I wrote, `一致したテキスト`, was made up) |
| `format.number` | `WFNumber` (**parameter slot = wrapped form**) · `WFNumberFormatDecimalPlaces` (**float**, e.g. `0.0` / `2.0`). The production idiom = `setvariable X → format.number(X) → setvariable X` **same-name write-back** (actions `[17-19]` of the bookkeeping shortcut); the output's `OutputName` = `フォーマット済みの数値` |

#### 7.8a `WFCondition` value table (condition codes of the If test)

**Before reading the table, know what it answers**: this table only answers "**this code is legal per the spec, and which keys it must be paired with**". It **cannot answer** "whether anyone has really used it successfully in the generation of the very file you are editing" —
that dimension can only be answered by `shortcut_action_index.py --param "conditional:WFCondition=<code>" --for <target file>`, **run it before starting** (the §7.9 ⑧a incident came from looking only at the first dimension).

**Source**: the third-party `viticci/shortcuts-playground-plugin`'s `CONTROL_FLOW.md` §Condition Codes (pinned to commit `2de03bf`, MIT, **third-party, hand-maintained, not Apple's original text**) + cross-checked against our corpus of real `.shortcut` files (`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/shortcut_action_index.py" | grep '^corpus ='` prints its current size).
The sample counts are **a single measurement, not constants**; to reproduce: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/shortcut_action_index.py" --param "conditional:WFCondition=<code>"`.

| Code | Meaning | Class | Extra required | Our samples (one measurement) |
|---|---|---|---|---|
| `0` | is less than (**less than, not equals**) | numeric | `WFNumberValue` | 1 (gen 1106) |
| `1` | ≤ | numeric | `WFNumberValue` | **0** `[third-party only]` |
| `2` | > | numeric | `WFNumberValue` | 1 (gen 900) |
| `3` | ≥ | numeric | `WFNumberValue` | **0** `[third-party only]` |
| `4` | is (string equality) | string | `WFConditionalActionString` | 26 (all gen 1106) 🔴 see the conflict below |
| `5` | is not | string | `WFConditionalActionString` | 3 (gen 1106) 🔴 same as above |
| `8` | begins with | string | `WFConditionalActionString` | 1 (gen 1106) |
| `9` | ends with | string | `WFConditionalActionString` | **0** `[third-party only]` |
| `99` | contains (substring) | string | `WFConditionalActionString` | 2 (gen 1106) |
| `100` | has any value | existence | (none, but extras are not forbidden) | 2 (gen 1106) |
| `101` | does not have any value | existence | (none) | **86** (5015×82 + 1106×4) ← the strongest in the whole table |
| `999` | does not contain | string | `WFConditionalActionString` | 1 (gen 1106) |
| `1003` | is between | numeric | `WFNumberValue` (lower bound) + `WFAnotherNumber` (upper bound) | 6 (all gen 5015) |

🔑 **The one statement in the whole table with no exception (129/129 measured on our files)**: **every code needs an explicit `WFInput`; there is no implicit-input mode**;
and all 129 are `Type=Variable` + an embedded `Variable` wrapper, with **zero** cases of a bare `WFTextTokenAttachment`.

🔴 **Three easy mistakes**: code `4` is exact equality and code `99` is substring containment, **not interchangeable** · code `0` is "less than", **not equals**, and `0`–`3` are all inequalities,
**modern conditional has no numeric "equals" code** (to test equality: use a multi-condition If with `≥` and `≤`, or treat it as text with code `4`) · codes `2`(>) and `3`(≥) differ only in whether the endpoint is included.

🔴 **One measured conflict, don't write a validator from the third party's version**: it says codes `4`/`5` must carry a non-empty `WFConditionalActionString` —
**15 of the 26 code-`4`s in that measurement don't** (14 have a `WFBooleanContentItem` coercion hung on `WFInput`, 2 use `WFNumberValue` to hold a literal).
⚠️ All 16 counterexamples are **in the same file** (a time-tracker shortcut, a third-party community artifact) → the characterization is "**it describes the accept set of its own validator; the real-device layer is wider**", not "the spec is wrong".

🔴 **One thing to look at before any of the above — our verification power is out of step with the current generation**:
**in that measurement, gen 5015 (the generation we are writing now) had only run through codes `101` and `1003`**, and the other 9 codes had sample count **0** in gen 5015;
the evidence for 8 codes in the table all comes from **one** gen-1106 community shortcut. **This is the same shape as the §7.9 ⑧a incident** —
so this table does not replace `--param … --for`; it is the step **before** that gate.
(Also a fact not recorded at the time: the 3 files of the bookkeeping shortcut series have a `conditional` count of **0**; after switching to 辞書 lookup not a single If remained.)

**Don't pile all the fields into this table** — it will go stale. To check whether precedent exists, first run `shortcut_action_index.py --list <keyword>`
(whether the action exists / what it is called); to see real field values, run `--dump <action>` for today's real sample.

### 7.9 Headless QA loop (distilled from hands-on work — reusable across products)

> **A destroy test can itself stop working**: the "two things differ" that a destroy depends on
> can be turned into "the same" by the next change → **the destroy idles while the corresponding must-pass still PASSes** (it doesn't go red — it **stops reporting**).
> → A destroy must **additionally assert the premise it depends on**: `assert locate_a() != locate_b()`.
> The question to ask: **could the "two things differ" that my destroy depends on become "the same" through the next change?**
>
> **Don't build probes by "modifying production"**: changing the production shape to make the probe run (e.g. swapping `ResultType`
> from `Dictionary` to `Text`) makes **the part that was changed a permanent blind spot**, while the green light looks the same.
> → Deviations must be **recorded machine-readably** (`DEVIATIONS = [(action, param, prod_value, variant_value, why)]`)
> and the report header must always print "⚠️ This variant does not cover: <deviation list>".


The real bottleneck of programmatic development isn't "can the file be modified" but **how to verify after modifying**. All of the following has been tested.

**① Import is the only manual step; everything else can be fully automated**

| What to do | Possible? | How |
|---|:---:|---|
| Modify the file (add/delete/change/reorder actions) | ✅ | plist operations + `shortcuts sign` |
| **Install into the library** | ❌ the CLI has no import | A human click can't be skipped, but **delivery is my job**: `open -a Shortcuts <file>` pops the "Add" dialog on the Mac · `SendUserFile` pushes it to the device the user is using (the Mac route is popped by `shortcut_build.write()` itself after passing the gates, §7.6). Both carry the plist md5 + a visually recognizable version feature. 🚩 The failure that has been verified is **walking neither** and stopping at "build shipped" — not choosing the wrong route |
| Run | ✅ | `shortcuts run <name> --output-path <f.txt>` |
| Read installed-but-never-exported | ❌ | `~/Library/Shortcuts/` is blocked by TCC |

> 🔴 **Measured: every retreat route is blocked too** (previously only "not in the CLI" was written):
> `~/Library/Shortcuts/` is **empty** (the library is not stored in a rewritable form; on macOS 27.2 even `ls` gives `Operation not permitted`) · `sign` only signs and does not install ·
> `view` accepts only **names already in the library** (no file paths). → **A human click is structurally unavoidable.**
>
> **That is exactly why the unit of versioning should change**: releasing one version per fix **charges the other person a click for every fix**.
> One session consumed **6** (v22/v23/v24/probe×2/variant) —
> of which the 3 of v22–v24 could have been bundled into the same round. **Batch up, and release together the next time the user has to click anyway.**
> The question to ask: **is this version worth a click? Can it be pressed together with the next fix?**

→ **Batch changes into one set before giving them to a human to import**, not one at a time (each is a manual interruption).

**② Headless probe pattern** — downgrade acceptance that "must be on a real device" into a machine judgment: swap the tested logic's input source for a **fixed file** (`documentpicker.open` reading `iCloud~is~workflow~my~workflows/Documents/<fixed name>`), send results through `--output-path`, and then use a Bash/Python loop to feed inputs + assert outputs. **Also build a "deliberately buggy control variant"**, so that "can detect green" and "can detect red" are proven at the same time.

Three measured pitfalls:
- ⚠️ The `--output-path` **extension must be `.txt`** — using `.out` **produces an empty file** (not no file), which is very easy to misjudge as a "lookup miss" and lead to changing the product while troubleshooting
- ⚠️ **Don't use `documentpicker.save` to write results in a probe** — it triggers the 「ファイルに保存することを許可しますか?」 authorization dialog, and **「常に許可」 measured as ineffective** (it pops on every run) → headless batch runs just hang
- ⚠️ **Change the shortcut name when the probe's shape changes** — re-importing under the same name leaves a copy in the library, and `shortcuts run <name>` will run on the **old one**, silently giving a stale result

**③ Three classes of bug, caught by machine assertion rather than discipline** (each hit once in practice)

| Class | Example | How to catch |
|---|---|---|
| **Cross-action type contract** | `format.date "HH"` produces `"07"`, an intermediate `math +0` turns it into `7`, while the 辞書 keys are two-digit strings → **00〜09 can't be found** (10〜23 are fine; a casual single test won't catch it) | Define "key production" and "the table's keys" **on adjacent lines of the same module**, then add a contract assertion |
| **A removed mechanism leaves an orphan dependency** | The only reason `+0` existed was to feed the If chain's numeric comparison; the If chain was deleted, and `+0` survived because it lay **outside** the deleted range | When deleting a mechanism, clean up its dependents by **causality**; don't delete only its own lines |
| **Identifier truncation** | Printing with `.split('.')[-1]` made `format.date` show as `date` → writing constants from the truncated display pointed at the wrong action | **Always compare the full identifier string**; don't trust the printed short name |

**④ Locating semantics must be split in two** (mixing them gives false alarms): **locating the target to modify** → must `assert` a unique hit (discipline 3); **taking a schema sample** → any one of the same type is equivalent, only assert ≥1. A file has 2 `documentpicker.open`s, and applying the former rule to it blows up directly.

**⑤ The regression suite and the wiring audit are complementary and can't substitute for each other**: `audit_wiring.py` catches generic wiring (cross-branch / dangling / unit) but can't catch **semantic regression** (e.g. "both branches merged" degrading to "bound directly to a single branch", where both happen to be inside the same branch). The product side should build its own per-story semantic invariants + a `must-pass`/`pending` two-state + a **destroy test** (deliberately break a file known to be green and see that the assertion really goes red — an assertion without a destroy test = an unverified detector). Precedent: the nutrition-log example's regression script.

**⑥ The suite's "negative-case file" pointer must advance together with each new invariant** —
the regression suite's `DEFAULT` constant often does two jobs: the default target with no arguments **+ the selftest's negative case** ("known good, must not be falsely flagged").
It was once found still pointing at v15, and v15 contains A9's forward-ref bug → the `IG-4` added the same day **correctly went red** on it,
but because it sat in the negative-case slot, it made `--selftest` **fail forever**. **The detector was right; the reference object was stale.**
→ When adding a new invariant, advance this pointer to the latest file that has passed the gate, otherwise the selftest becomes routine noise and the next person learns to ignore it.

**⑦ A gate must be built as structure, not only as discipline** — the V4 gate states in black and white "if any must-pass fails → stop, don't export",
but the discipline was violated by ourselves (the import dialog popped before the gate ran). **The fix: write the gate into the generator — if `_gate()` fails it raises `SystemExit`,
so the official file structurally cannot be written out**, and **run it once per stage rather than once at the end**.
Companion: the generator is run twice in a row, asserting that the `WFWorkflowActions` plist **md5 is exactly identical** (idempotence = rerunnable, no random drift).

**⑦a Write order: temp file → all gate checks → `os.replace`** — ⑦ said "structurally cannot be written out"; this is how it is done:

```python
tmp = OUT.with_name(OUT.stem + ".tmp" + OUT.suffix)
try:
    save_shortcut(plist, tmp)
    _gate(open_shortcut(tmp)["WFWorkflowActions"], src_types)   # gate check by reading back after writing to disk
    _regression_gate(tmp)                                       # regression suite, nonzero exit → SystemExit
    os.replace(tmp, OUT)
finally:
    tmp.unlink(missing_ok=True)
```

**Why it can't be "write the official file → read back → report an error"**: when the read-back fails the bad file is already on disk, and the next step is usually `open -a Shortcuts` to have a human click import = making the user click something unverified. The first implementation was a bookkeeping shortcut's build script; the shared version = `write()` in `${CLAUDE_PLUGIN_ROOT}/scripts/shortcut_build.py`.
🚩 **One-line self-check**: `grep -rn "<check script name>" <generator>` — 0 hits means a check script was written but nothing calls it.

**⑦b The idempotence criterion may compare only the plist md5, not the file md5** — `shortcuts sign` **produces different bytes on every signing**, so the `.shortcut` file's own md5 changes even on the normal success path, and comparing it is as good as not comparing. The "`WFWorkflowActions` plist md5" in ⑦ above is the only valid criterion (`plistlib.dumps(acts, fmt=FMT_BINARY)`).
**A destruction test likewise must be split into two tests, don't let one stand in for two**: "is the gate wired correctly" = swap the callee for a stub that surely returns nonzero and see whether the official file moved (compare plist md5 byte for byte); "does the criterion have teeth" = the negative case of that check script's own `--selftest`.
**The other half of the solution: when writing to disk, also keep a copy of the unsigned XML original as the diff baseline** — md5 answers "are these two versions the same", XML answers "**which key of which action differs**", which a human can read, diff, and paste into a review. They complement, not exclude, each other.
Source: the third-party `viticci/shortcuts-playground-plugin` marks this step as a mandatory slot in its body (`Archive Raw XML (Required)`). **We have not landed this yet**; recorded here as an existing form.

**⑧ ⚠️ The corpus is alive and contains your own output** — `shortcut_action_index.py --check <action>` counts
**the file you just generated and wrote to disk this round** into the sample count. Measured: `--check format.number` reported "5 samples",
of which **4 were the artifacts just written**, and the really pre-existing samples were only 1 (and its parameter values were not the ones to be used either).
→ **The conclusion "samples exist" gets polluted by yourself**, and §7.3/§7.4 discipline 1 relies entirely on it.
The question to ask: **"of these N samples, how many existed before I started?"** For evidence, either scan before writing, or exclude your own artifacts by file name.

**⑧a The sample count has a second dimension: the client generation. And what you need to ask about is often not the action but "a parameter taking a certain value"** (learned from an incident, since built into the tool)

`--check <action>` works at the granularity of the **action identifier**. What you really need to copy is usually **one value of one parameter**, a layer it can't answer:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/shortcut_action_index.py" --param 'ACTION:KEY=VALUE' --for <target.shortcut>
```

Grouped by `WFWorkflowMinimumClientVersion`, it reports total samples / of which written to disk in the last 24h / existing before you started; when `--for` is given it reads the target file's own generation, and **if that generation's samples existing before you started = 0 it prints 🔴 and exits nonzero**.

> **Incident**: for `conditional`'s `WFCondition=4` (文字列が等しい) I counted "26 samples" with a hand-rolled scan and went ahead — those 26 **all belong to gen 1106**, while the target (a bookkeeping shortcut) is gen 5015, and **that generation has not a single real sample** (the only one was the artifact I had just generated). Copying the parameter in didn't work on a real device; it only worked after switching to a 辞書 lookup.
> **The hand-rolled one also lost ⑧'s self-pollution annotation** — the protection the ready-made tool has, absent from the ruler I whittled up on the spot.
> 🚩 **Red flag: about to write a one-off scan while a mature tool already exists in the same problem domain and merely can't answer this granularity.** First open it and list the protections it has, and ask of each "do I need this in mine?"

### 7.10 Division of labor between human and machine — what **must** a human do, what should a machine do (measured boundaries)

> **Why this gets its own section**: the biggest hidden cost of programmatic development is not writing code, it is **wrongly throwing automatable things to a human**.
> One triage cut the AI Diet Log's real-device tests from **10 check items to 5 runs** —
> what was cut was not "unimportant"; it was **what should have been run by machine all along**. Triage saves more human effort than writing more tools.

#### A. Hard boundary: **four classes + two items** that only a human can do (all measured, not quoting old conclusions)

| Class | Specifics | Measured evidence |
|---|---|---|
| **Import** | Install the `.shortcut` into the library | `shortcuts --help` has only `run/list/view/sign`, **no import**. A human click can't be skipped — but **delivery is my job**: when the user is at the Mac use `open -a Shortcuts <file>`, when not use `SendUserFile` to push it to the user's device (see §7.6). 🚩 Red flag: about to write "the file is in the project folder, go and tap `<path>`" — that turns a delivery action I can do into a manual step for the user |
| **Read installed content** | Read any shortcut in the library that was never exported | `~/Library/Shortcuts/` + `group.com.apple.shortcuts` + `group.is.workflow.{my.app,shortcuts}` **all four paths give `Operation not permitted`** (TCC). **No CLI export** → only a human can do 「共有 → ファイルを書き出す」 |
| **Health real write-in** | Verify the fields were really written to Health | **macOS has no Health app** → only an iPhone visual check |
| **Health read-back / search** | Any chain using `filter.health.quantity` (`ヘルスケアサンプルを検索`) | 🔴 **Stricter than "the Mac has no Health app": this action is simply unsupported on the Mac** (measured: the probe couldn't even run). → **To test its downstream guard semantics in isolation on the Mac, you can only replace the upstream** — use "read a nonexistent file" to produce a no-value fed into the same condition (that is how `probe-cond101` verified `WFCondition=101 = has-no-value` in both directions). **Don't treat "can't run on the Mac" as "can only wait for a real device"** |
| **Camera framing** | Photograph real food / a nutrition facts table | A physical action. iPhone Mirroring doesn't work either (it requires the iPhone to be locked and set aside) |
| **Photo library / screenshot interaction** | `selectphoto`'s picker, `takescreenshot` | Interactive |
| **UI rendering judgment** | Card layout / Japanese line breaks / overflow | The machine can't see it without 画面収録 permission (see D) |

#### B. Confirmed **automatable** (stop throwing these to a human)

- **Execution**: `shortcuts run <name> --output-path <f>` runs an installed shortcut headlessly
  - ⚠️ **The `--output-path` extension must be `.txt`** — using `.out` **produces an empty file** (not no file), which is very easy to misjudge as a business bug when troubleshooting
  - ⚠️ **Ban `documentpicker.save`** inside probes (authorization dialog + 「常に許可」 measured as ineffective) → use `--output-path` to get the result
- **AI steps**: **the Mac can run `askllm` headlessly** (measured: exit 0, output as expected) → JSON well-formedness rate / missing fields / whether the prompt's hard constraints take effect, **none need to wait for a real device**
- **Any pure lookup / pure arithmetic / pure text assembly**: build it as a headless probe (§7.9 ②)

> ✅ **Measured on macOS 27.2: `health.quantity.log` fails loudly on the Mac — it is not a silent no-op.** The probe `probe-health-log-mac` (one `health.quantity.log`, Fiber 1 g, then a text action), run via `shortcuts run … --output-path <file>.txt`, gave exit 1, stderr verbatim `Error: アクション“ヘルスケアサンプルを記録”はMacには対応していません。`, and no output file. So on the Mac it fails loudly rather than silently doing nothing; Health checks stay on the iPhone.

#### A′. iOS **content-level lineage tracking** — a class of mandatory manual work that "never shows up on the Mac"

> The A table above lists "things the machine **cannot do**". This item is different: the machine can do it, **but iOS actively inserts a prompt for a human to click**,
> and **clicking 「常に許可」 has no effect**. It appears in no static check, and a headless Mac run 100% fails to reproduce it.

**Phenomenon** (AI Diet Log A10): for every **new photo** taken, the calendar step pops
「〈shortcut name〉が **1枚の写真をカレンダーの新規予定で使用する**ことを許可しますか?」 once —
clicking 「常に許可」 **doesn't carry over across photos**, and the next photo pops it again. It only shows when several photos are taken in a row, and **a single run won't reveal it**.

**Explanations ruled out** (all tested, don't walk this again): there is **no photo reference** in the calendar action's title/notes/calendar name
(all ordinary variables + `getvalueforkey` output) · across the whole file the 「画像」 variable is referenced only by the two `askllm`s ·
the previous action is an ordinary `gettext`.

**The remaining explanation = iOS tracing by content lineage**: the value was derived from the photo via `askllm`, and when it is written into a calendar event
the system still considers "this event is using that photo", so it **asks once per photo**.
⚠️ **Not fully established** (control group: the same values written to Health are asked **only once**, the difference is not established) —
so the workaround below is currently only a **candidate**, not the answer.

**Design inferences (transferable, not limited to this product)**:

1. **Writing "a value the AI derived from user content" into another privacy-protected destination** (calendar / contacts / reminders…)
   → expect it to trigger **per-content** authorization rather than one-time authorization. Design as if it will pop; don't wait for a real device to find out.
2. **Direction of workaround = cut the lineage**: before writing, launder the value into "plain text unrelated to its source" (candidate: `テキストを置換`).
   ⚠️ Protocol §7.4 — no sample, no schema guessing; first obtain that action's corpus.
3. **Stopping the bleeding is always an option**: deleting that write action = a fully reversible downgrade (this product's v17 did exactly that, machine gate 12/12).
   One feature fewer ≫ a dialog on every photo.
4. 🔴 **This kind of problem can only be caught by "running several times in a row"** — a single-run real-device acceptance is blind to it.
   For any step in the human checklist that "uses user content every time", write "run 3 photos in a row" rather than "run once".

#### C. Triage criterion (ask before starting each real-device case)

```
Does this case depend on any of the following?
  Health real read/write / camera framing / photo library·screenshot interaction / iOS settings layer / UI rendering appearance
├─ yes → give it to a human. And **merge similar ones**: if several check items can be glanced at in the same run, count them as one
└─ no  → give it to the machine: build a headless probe (swap the input for a fixed file + take the result via --output-path)
         and pair it with a **deliberately buggy control variant**, so "can detect green" and "can detect red" are proven at the same time
```

**Three easily overlooked triage disciplines**:

1. 🔴 **Separate "the capability of a vendor-native action" from "our wiring" — only the latter is an acceptance item**
   Whether a native action (`selectphoto` / `takescreenshot` / `takephoto` / `askllm` …) **works well itself is not our KPI**
   (same origin as "AI recognition accuracy is not a KPI"). What to verify is only **whether we wired it correctly**, and wiring is **machine-verifiable**
   (who wrote which variable, on which branch, whether the downstream reads the same variable).
   → **Corollary: for enumerations such as an "entry axis / type axis", if the flow after each branch is exactly the same and the wiring is machine-verified, there is no need to run every branch on a real device.**
   The axis-enumeration discipline guards against **wiring** bugs (a branch bound wrong → testing only one path can't find it), not against "Apple's action might break".
   **Additional evidence source**: if the corpus already holds a same-shape flow **in production use** (such as a bookkeeping shortcut's `selectphoto → 変数「画像」→ askllm`),
   that itself is evidence the shape works, and there is no need to have a human verify it again.
   > sourceIncident: I put "run each of the 3 entries once" into the human checklist, and the user asked back
   > 「这些都 apple shortcut 自己的功能，不涉及我们的开发逻辑或者 integration，需要我验证？？？」 [These are all Apple Shortcuts' own features and don't involve our development logic or integration — do I need to verify them???]
   > — after triage, 5 runs were cut again to 3. **Mechanically copying the axis enumeration = treating a vendor capability as our own acceptance item.**

2. **Organize the human checklist by "number of runs", not by "check items"** — of 10 check items there are often only a few real runs, and the rest are glanced at in the same run. Listing by check item makes people think the workload doubled.

3. **Read the probe's expected values from the shipped file**, don't write a separate copy — a separate copy is bound to drift from the real thing, and what gets tested becomes "what I think it should be".

#### D. Optional levers (trade a permission for a whole class of manual work, each with a different cost)

| Permission | What it replaces | Cost | Status |
|---|---|---|---|
| **Full Disk Access** | **The whole B class "read installed content" disappears** — every shortcut in the library enters the corpus automatically, and no more asking people to export | Whole-disk **read-only** (including TCC areas such as mail/messages/Safari history) | Not enabled; every missing action schema requires asking a human to export once |
| **画面収録 (Screen Recording)** | UI rendering judgment + diagnosing "phenomena that are hard to describe" (it happened that day: only a human screenshot identified it as the file-save authorization dialog) | Can capture the whole screen | Not enabled |
| **アクセシビリティ (Accessibility)** | In theory it can auto-click iPhone Mirroring | **Can control any app**, a higher level of risk; and whether Mirroring accepts synthetic events is **unverified** | Not enabled, **not recommended** — what it could replace (repetitive matrices) is done better with headless probes, and what it can't replace (camera / Back Tap) it can't do either |

### 7.11 Where values come from: dig into the system framework first, then ask

**Trigger**: you need an **enum value** (`WFQuantitySampleType` / condition code / unit enum) and the corpus has no sample.
**Don't reflexively ask a human to build a shortcut and export it** — the system framework may already contain the full table.

1. **How to dig**: `HealthKit.framework/Versions/A/Resources/Localizable-DataTypes.loctable`
   (one entry set per language, a binary plist, readable directly with `plistlib.loads`;
   `python3 -c "import plistlib,pathlib;t=plistlib.loads(pathlib.Path('/System/Library/Frameworks/HealthKit.framework/Versions/A/Resources/Localizable-DataTypes.loctable').read_bytes());print(len(t), len(t['en']))"` prints the language count, then the entry count).
   **Reverse-look up English from Japanese** (the UI is Japanese, the parameter needs an English string): find the `ja` value == the word you see → read the `en` value under the same key.
2. ⚠️ **Only 3/4 are reliable; a candidate ≠ a confirmed value**: `炭水化物→Carbohydrates` ✅ `タンパク質→Protein` ✅
   `総脂肪→Total Fat` ✅ but **`摂取エネルギー→Dietary Energy` ❌** (on a real device it is actually `Dietary Calories`).
   → **Shortcuts has its own set of names, which are not necessarily the system App's display names**. What you dig up must be verified on a real device (pair it with the control-group method of §7.9②).
3. **`strings` on the framework binary is useless**: modern macOS frameworks live in the **dyld shared cache**, and under the path there is a stub.
   To find strings, look for the **resource files** (`.loctable` / `.strings` / `.plist`), don't `strings` the binary.
4. **Payoff**: one request "you build 5 actions and export them" was compressed into "open one file and look at 4 lines".

**Two companion disciplines**:

- **New platform capabilities often come with permission switches** — the write permission of newly added Health categories (食物繊維/ビタミンC/カリウム)
  is **off by default** (the real device prompts 「カリウムへのアクセスがオフです」) → **even with the right value the data can't get in**.
  When adding a new field / new integration, **always check the permission default once**, and write it into the deployment preconditions.
- **The same "value set" often has multiple surfaces** — example: `audit_wiring.py`'s `EXPECTED_UNIT` (is the unit right) once also had
  a C5 scan key table (does the prompt contain this key) as a second consumer, and D-25 only extended the former → C5 reported the 3 new items all as false positives.
  That key table has since been deleted: C5 now takes the key directly and looks for `"<key>"` in the upstream askllm's prompt, with no second list;
  `EXPECTED_UNIT` is still imported by the product regression script. **Before changing an enum, grep all of its consumers.**

---

## Related

**The four tools of §7 (platform-level, `${CLAUDE_PLUGIN_ROOT}/scripts/`)**:
- `shortcut_io.py` — read/write library + `--tree` (control-flow structure) / `--prompts` (AI prompt dump)
- `audit_wiring.py` — static wiring audit C1–C6 + `--selftest`
- `shortcut_action_index.py` — **corpus index**: `--check <action>` whether a sample exists / `--dump <action>` see the real schema. **Run it before you start** (§7.3)
- `shortcut_build.py` — patch-script helpers + the `write()` write gate (gate checks → `os.replace` → delivery) + `--selftest`
