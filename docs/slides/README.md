# Slides

`ragnarok-architecture.pdf` — an overview deck covering Ragnarok's architecture,
what you can do with it, and how to build a plugin. Hand it to a new teammate or
present it as a quick intro.

It is generated from `build_deck.py` (pure matplotlib, no external converter).
To rebuild after editing the script:

```bash
# any Python with matplotlib (e.g. the project venv)
python docs/slides/build_deck.py
# -> docs/slides/ragnarok-architecture.pdf
```

Keep `build_deck.py` as the source of truth and re-run it rather than editing the
PDF by hand.
