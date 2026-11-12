# Prompt 1: build the assignment

This is the exact instruction the coordinating Claude Code session gave the subagent that built this submission. It was sent on 2026-11-10 to a built-in `general-purpose` subagent with default settings. The coordinating session sent the same prompt, changed only for each task, to one subagent per starter-pack task.

---

You are completing ONE take-home assignment from a Junior AI Engineer starter pack: the **invoices** task ("AI Invoice Reconciliation & Review Platform").

## Sources (read these first, fully)
- Brief: `C:\Users\HP\Desktop\prov\client-ai-project-research.html` — read the sections whose ids start with `invoices-` (overview, dataset, requirements, generation, optional, evaluation, submission, philosophy). Also skim the general "Choosing and assessing an assignment" section for what assessors look for.
- Task folder: `C:\Users\HP\Desktop\prov\client-ai-starter-pack\client-ai-starter-pack\tasks\invoices\` — read `domain.md` and every file in it (look at the invoice images too).
- Pack README: `C:\Users\HP\Desktop\prov\client-ai-starter-pack\client-ai-starter-pack\README.md`
- Data skill: `C:\Users\HP\Desktop\prov\client-ai-starter-pack\client-ai-starter-pack\skills\generate-assignment-data\SKILL.md` (use it if you need more fixtures; it does not build the app).
- AI workflow templates: `C:\Users\HP\Desktop\prov\client-ai-starter-pack\client-ai-starter-pack\ai-workflow\`

## Rules
- Write everything into `C:\Users\HP\Desktop\prov\submissions\invoices\`. Do NOT modify anything under `client-ai-starter-pack/` — copy what you need.
- Preserve the supplied domain rules and cases exactly; do not invent business policies.
- **The final code must be easy to read**: small focused modules and functions, clear names, plain control flow, no clever abstractions or unnecessary layers, brief comments only where the "why" isn't obvious. Prefer the standard library; keep dependencies minimal. Favour a simple design a reviewer can follow in one sitting over feature breadth.
- Environment: Windows, Python 3.12 (`python`, Anaconda) and Node available. No model API key is available, so any LLM/vision step must have a deterministic offline path (e.g. reading the structured invoice JSON alongside images, or a clearly marked stub/provider interface) so the app and tests run without a key; keep the LLM integration optional and behind a small interface reading `MODEL_API_KEY` from env.
- Include automated tests, including a check that the app reproduces `expected-seed-results.json` for the supplied seeds. Run them and make them pass. Also run the app once end to end.
- Copy `ai-workflow/` into the submission, rename the template files, and fill them in honestly (this agent session was the AI tool used; record `not-used` for custom skills/agents/hooks you didn't use).
- Include a short README: how to run, design, how the domain rules map to code, limitations.
- Respect the brief's scope (an ~8-hour assignment). Don't ask questions; make sensible choices and note them in the README.

## Final report (keep it under 200 words)
What you built, the files layout, exact commands to run app and tests, the test results you actually observed, and any deviations or gaps.
