# NexAI Reliability Demos

These flows are meant to demonstrate grounded local-agent behavior through the real `/v1/chat` and agent runtime path.

## 1. Read a file and summarize it

- Request: `create a file named demo.txt with content hello`
- Expected tool path: `fs.write_text`
- Request: `summarize demo.txt`
- Expected tool path: `fs.read_text`
- Success looks like:
  - `demo.txt` exists
  - the response includes `fs.read_text: OK`
  - the response includes actual file-backed content, not a guessed answer

## 2. Find where a feature is implemented in the repo

- Request: `Inspect the repo and tell me where delete is implemented`
- Expected tool path: `fs.grep`
- Success looks like:
  - the response includes `fs.grep: OK`
  - matching file paths are returned from the local repo
  - no generic explanation is returned before inspection

## 3. Edit code or text and confirm the change

- Request: `edit demo.txt and replace its contents with hello again`
- Expected tool path: `fs.write_text`
- Success looks like:
  - the response includes `fs.write_text: OK`
  - reading the file afterwards returns `hello again`

## 4. Delete a file and verify deletion

- Request: `delete demo.txt`
- Expected tool path: `fs.delete`
- Success looks like:
  - the response includes `fs.delete: OK`
  - the file no longer exists
  - if deletion fails, the response reports the real error instead of claiming success

## 5. Explain a planner/runtime behavior from inspected code

- Request: `Show me how tool execution results are represented`
- Expected tool path: `fs.grep`
- Success looks like:
  - the response includes matches for `ToolResult`
  - the agent reports local file paths or lines instead of making framework assumptions

## 6. Fail safely when the target is ambiguous

- Request: `show the file I just created`
- Expected behavior:
  - if there is an unambiguous recent file in working memory, NexAI reads it with `fs.read_text`
  - otherwise NexAI returns a grounded clarification
- Success looks like:
  - no invented file contents
  - no fake capability denial such as `I can't access your files`
