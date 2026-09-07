# Kiongozi V2 🇰🇪

**Know Your Leaders. Understand the Data.**

Kiongozi is a neutral leaders-evaluation platform for Kenya.

## V2 fixes

- Automatically imports National Assembly records when the app database is empty.
- Works correctly with Gunicorn/Render; the previous version only imported leaders when `python app.py` was run directly.
- Handles Parliament's paginated members directory instead of reading only one page.
- Uses a defensive HTML parser that finds columns by their headers.
- Includes a fallback Parliament URL.
- `/health` reports the current number of imported leaders.
- Manual refresh remains available at `/refresh`.

The National Assembly directory is the official source used for the imported member records.

## Run locally

```bash
pip install -r requirements.txt
python app.py
```

Open:

`http://127.0.0.1:5000`

## Render

Build command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
gunicorn app:app
```

Optional environment variable:

```text
PYTHON_VERSION=3.13.5
```

After deployment, open `/health` to confirm that the application reports a non-zero `leaders` count.

## Important data note

V2 imports National Assembly records from Parliament of Kenya. It does not invent performance scores. Evaluation scores must be supported by evidence and entered through the evaluation system.

The next production phase can add official Senate, Governor, Woman Representative and MCA data sources, plus evidence-based attendance, bills, projects, budgets and promise tracking.
