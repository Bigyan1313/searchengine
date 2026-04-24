# Lyricly - Keyword Search Project

Flask + Whoosh search application with two modes: web search (Brave API) and local lyrics search.

## Layout

```
search_project_clean/
|- app.py                  # Flask app routes and search APIs
|- build_index.py          # builds Whoosh index from data/lyrics.csv
|- data/lyrics.csv         # source dataset
|- templates/              # HTML templates (index, song, 404)
|- static/style.css        # UI styles
|- requirements.txt        # Python dependencies
|- Procfile                # process command for platform deploys
|- nixpacks.toml           # Railway build/start config
|- render.yaml             # Render config
|- summary.txt             # project summary
`- .gitignore
```

## Running locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python build_index.py
python app.py
```

Open: http://localhost:5000

## How the program works

The homepage provides one search box and a mode switch.  
In Web mode, the app sends queries to the Brave Search API and returns web results.  
In Local mode, the app searches a Whoosh index built from `data/lyrics.csv`.  
Local results are ranked with BM25F and include highlighted snippets around matched terms.  
Clicking a local result opens a full song page with title, artist, year, rank, and lyrics.
