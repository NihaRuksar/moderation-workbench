# AI Agent Usage

## Tools
- **Claude (chat):** planning, per-file specifications, code, code review, test writing, README drafts.
- **Groq with `openai/gpt-oss-120b`:** the model the app itself uses to review content. It is a product feature, not a development tool.


## Representative prompts
- Asked which option to choose, Medium or Expert, given the scoring and the 48-hour window.
- Asked for a file-by-file specification so I could write the code myself.
- Pasted my own files (`database.py`, `config.py`) for review.
- Asked for complete code for the larger files, such as the services and templates.
- Asked "what did we do in this file?" after each batch, to prepare for explaining it.
- Pasted terminal errors and asked for the cause.

## What I delegated and what I did myself
- **Delegated to the agent:** the build plan and batch order, file specs, most service and route code, the HTML templates, the tests, and README drafts.
- **Did myself:**  environment setup, Groq key, running and testing every batch, git, and deployment.
- I read and ran every batch, and used the "what this file does" explanations to understand the code.

## Agent mistakes and suggestions I rejected
- **First recommendation was too cautious.** The agent suggested Medium partly because of time risk. I pointed out that Expert fits in 48 hours, and the recommendation was corrected.
- **Model name did not work.** The suggested Groq model was not available on my key and returned `NotFoundError`. The fallback handled it without crashing. I listed the available models and switched to `openai/gpt-oss-120b`.
- **Models I rejected:** the safeguard and prompt-guard models (built for classification, not general review), and an unfamiliar model whose JSON behavior I could not trust.
- **Review caught problems in my code:** a hardcoded database URL in `database.py`, a missing `get_db()`, and a missing `import os` in `config.py`.
- **Deployment platform changed** because the Railway trial ended, so I moved to Render.
- [Add this only if true: I pasted my API key into chat by mistake, so I revoked it and created a new one.]

## How I verified the output
- 20 automated tests (`pytest -q`) with a fake AI, so no key or network is needed.
- A manual test checklist after every batch, using `/docs` and the web pages.
- Fallback test: ran with a wrong key and confirmed the item still reached the queue as "escalate", with a human required.
- Checked the database directly for policy version ids, moderation history after an overturned appeal, and audit entries.
- Confirmed the key was never committed with `git log -p --all | findstr "gsk_"`, which returned nothing.
- Clicked through the live deployed app end to end.
