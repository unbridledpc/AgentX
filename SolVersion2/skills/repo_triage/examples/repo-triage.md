Example:

Goal:
- "Inspect this repo, find the backend entrypoint, then summarize likely failure points."

Suggested flow:
- `fs.list`
- `fs.read_text`
- `fs.grep`
- summarize findings before any write
