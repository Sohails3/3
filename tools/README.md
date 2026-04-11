# Tools

Python scripts for deterministic execution. Each script should:
- Load credentials from `.env` (use `python-dotenv`)
- Accept inputs via CLI args or stdin
- Write outputs to `.tmp/` or directly to a cloud service
- Exit with a non-zero code on failure

## Running a tool

```bash
python tools/<script_name>.py
```
