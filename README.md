# League of Legends Personal Analytics Pipeline

Learning-first scaffold for a Riot API ELT pipeline:

- Extract match history from Riot API (incremental via watermark)
- Land raw JSON in PostgreSQL
- Transform your own participant stats into a staging table
- Prepare for downstream dbt + BigQuery modeling
- Practice core DE concepts incrementally with checkpoints

## Project structure

```text
.
├─ main.py
├─ requirements.txt
├─ .env.example
└─ src/
   └─ lol_pipeline/
      ├─ api_extractor.py
      ├─ api_transformer.py
      ├─ api_loader.py
      ├─ config.py
      └─ storage.py
```

## Setup

1. Create a virtual environment and install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in values.

3. Ensure PostgreSQL is reachable by `POSTGRES_DSN`.

## Run

- Foundations learning checkpoint:

  ```bash
  python main.py --check-foundations
  ```

- Incremental mode (default):

  ```bash
  python main.py --mode incremental
  ```

- Backfill mode:

  ```bash
  python main.py --mode backfill --backfill-limit 500
  ```

## Guided learning flow

1. Run `--check-foundations`
2. Run `--mode backfill` once to seed raw data
3. Run `--mode incremental` repeatedly and observe watermark behavior
4. Inspect `raw_matches`, `etl_watermark`, and `stg_match_participant_self`

## Current schema (PostgreSQL)

- `raw_matches` (JSONB landing table)
- `etl_watermark` (incremental checkpoint)
- `stg_match_participant_self` (flattened self-performance rows)
