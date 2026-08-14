# IELTS Prep Bot 🎓

A Telegram bot for practising all four sections of the IELTS exam —
**Reading, Listening, Writing and Speaking** — plus vocabulary flashcards and
progress tracking. Built with Python and [aiogram 3](https://docs.aiogram.dev/).

## Features

| Section | Bank | What you get |
|---|---|---|
| 📖 **Reading** | 6 passages · 33 questions | Academic passages with auto-checked questions, each with an explanation. |
| 🎧 **Listening** | 6 exercises · 29 questions | Delivered as a **voice clip** (synthesized with gTTS) or transcript, followed by questions. |
| ✍️ **Writing** | 8 tasks | Academic Task 1 & 2 plus a General Training letter. Send your essay and get **examiner feedback** — AI-graded against the band descriptors if an Anthropic key is set, otherwise a built-in rule-based estimate. |
| 🗣 **Speaking** | 9 sets · 26 prompts | Parts 1–3 with cue cards and model tips. Reply by voice or text. |
| 🔤 **Vocabulary** | 7 decks · 41 cards | Flip-card decks: trends language, linkers, topic vocabulary, idioms, phrasal verbs. |
| 📊 **Progress** | — | Per-section attempts and scores, stored in SQLite. |

**Question types supported:** multiple choice, TRUE/FALSE, TRUE/FALSE/NOT GIVEN,
YES/NO/NOT GIVEN and gap fill (with a list of accepted answer variants).

## Quick start

```bash
# 1. Install dependencies
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
#   → open .env and paste the token you get from @BotFather

# 3. Run
python -m app.main       # or: python run.py
```

Then open your bot in Telegram and send `/start`.

## Configuration (`.env`)

| Variable | Required | Purpose |
|---|---|---|
| `BOT_TOKEN` | ✅ | Bot token from [@BotFather](https://t.me/BotFather). |
| `ANTHROPIC_API_KEY` | — | Enables AI-graded Writing feedback. Without it a rule-based evaluator is used. |
| `ANTHROPIC_MODEL` | — | Model for AI feedback (default `claude-sonnet-5`). |
| `DB_PATH` | — | SQLite file path (default `data/ielts.db`). |
| `TELEGRAM_PROXY` | — | Proxy for `api.telegram.org` if it is blocked on your network. Needs `pip install aiohttp-socks`. |

If the bot cannot reach Telegram it exits with a clear message rather than a
traceback, so a network problem is never mistaken for a bug in the code.

**Optional extras** — install to unlock more:
- `gTTS` → real voice clips in the Listening section (falls back to transcript text otherwise).
- `anthropic` → AI-graded Writing feedback.

## Running with Docker

```bash
cp .env.example .env          # paste your @BotFather token into BOT_TOKEN
docker compose up -d --build  # build and start
docker compose logs -f        # watch it connect
```

A successful start logs `Started as @yourbot (id=…)`. To stop: `docker compose down`
(add `-v` to also delete the database and cached audio).

Notes on the setup:

- **The token is never baked into the image.** `.env` is listed in
  `.dockerignore` and passed at runtime via `env_file`, so the image stays safe
  to push to a registry.
- **Data survives rebuilds.** The SQLite database and the cached TTS audio live
  in named volumes (`ielts-data`, `ielts-media`) rather than in the container.
- **Content is validated at build time.** A broken JSON edit fails
  `docker compose build` instead of surfacing at a learner's first request.
- **The container runs as an unprivileged user** (`ielts`, uid 1000).
- Logs are capped at 3 × 10 MB so a long-running bot cannot fill the disk.

Useful one-offs:

```bash
docker compose run --rm bot python scripts/validate_content.py
docker compose run --rm bot python scripts/demo.py reading r4 --auto
```

## Testing it without Telegram

You do not need a bot token to check that everything works.

```bash
# 1. Validate every exercise file (ids, answer indexes, missing fields…)
python scripts/validate_content.py

# 2. See everything in the bank
python scripts/demo.py

# 3. Play an exercise in the terminal — same content and grading as the bot
python scripts/demo.py reading r4
python scripts/demo.py listening l3
python scripts/demo.py writing w3
python scripts/demo.py speaking s6
python scripts/demo.py vocabulary v3

# 4. Non-interactive self-test: answers each question with the declared
#    correct answer and fails if any of them is not graded as correct
python scripts/demo.py reading r4 --auto
```

Both scripts exit with a non-zero status on failure, so they can be dropped
straight into CI.

## Project layout

```
app/
├── main.py            # entry point: wiring + polling
├── config.py          # env-based configuration
├── db.py              # SQLite (users, results, stats)
├── states.py          # FSM states
├── keyboards.py       # menu & inline keyboards
├── content/           # exercise data as JSON — edit to add more
│   ├── reading.json
│   ├── listening.json
│   ├── writing.json
│   ├── speaking.json
│   └── vocabulary.json
├── services/
│   ├── content.py     # loads/looks up exercises
│   ├── grading.py     # answer checking (no aiogram — reusable & testable)
│   ├── tts.py         # optional text-to-speech (gTTS)
│   └── evaluation.py  # essay grading (AI or rule-based)
└── handlers/          # one router per section
    ├── quiz.py        # shared Reading + Listening engine
    ├── writing.py
    ├── speaking.py
    ├── vocabulary.py
    ├── progress.py
    └── common.py      # /start, /help, /cancel, fallback

scripts/
├── validate_content.py  # content integrity check (CI-friendly)
└── demo.py              # play any exercise in the terminal

Dockerfile               # unprivileged image, validates content at build time
docker-compose.yml       # named volumes for the DB and audio cache
```

## Adding content

Every exercise lives in a JSON file under `app/content/`. To add a Reading
passage, append an object to `reading.json` with a unique `id`, a `passage`,
and a `questions` list. No code changes needed — the bot picks it up on restart.

A question object looks like this:

```jsonc
{ "type": "mc",   "q": "…", "options": ["A","B","C"], "answer": 1, "explanation": "…" }
{ "type": "tfng", "q": "…", "answer": "NOT GIVEN", "explanation": "…" }
{ "type": "ynng", "q": "…", "answer": "NO", "explanation": "…" }
{ "type": "gap",  "q": "…", "answer": "45", "accept": ["forty-five"], "explanation": "…" }
```

Run `python scripts/validate_content.py` after editing — it catches out-of-range
answer indexes, illegal labels, duplicate ids and missing explanations.

## Notes

- Speaking answers are collected as voice/text and the bot responds with model
  tips; automatic speech scoring is intentionally out of scope for this version.
- The rule-based Writing band estimate checks structure and length only; use an
  Anthropic key for feedback on grammar, vocabulary and argument quality.
