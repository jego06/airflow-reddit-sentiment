# Reddit Sentiment Live Monitoring ETL Pipeline

This project deploys an **Airflow-orchestrated Data Engineering pipeline** for the **live monitoring** of Reddit sentiment. It uses the PRAW library to scrape the newest posts, performs VADER sentiment analysis, and loads the results into a PostgreSQL database using a robust **UPSERT (Update or Insert)** mechanism to prevent duplicate data.

--------- INSERT HERE REAL TALK ----

The pipeline is intentionally streamlined to focus only on retrieving the most recent posts ($\sim 1,000$ posts per run) from a specified subreddit.

## 1. Project Architecture and DAG Overview 📊

The system uses the official Airflow Docker Compose stack to run a Celery Executor cluster alongside a PostgreSQL database and a Redis broker.

| Component | Purpose | Technology | Key Feature |
| :--- | :--- | :--- | :--- |
| **`subreddit_sentiment_analysis`** | **The ETL Pipeline.** Orchestrates the entire data flow. | Apache Airflow | Manual Trigger (`schedule=None`) |
| **Data Extraction** | Scrapes the "new" posts from the Reddit API. | PRAW via Airflow `BaseHook` | Uses batching to overcome PRAW's $\sim 1,000$ post limit. |
| **Data Transformation** | Calculates four distinct sentiment scores. | VADER (nltk) | Provides `compound_score` for normalized overall sentiment. |
| **Data Loading** | Writes data atomically to the final table. | PostgreSQL + `psycopg2` | Implements **`ON CONFLICT (post_id) DO UPDATE`** (UPSERT). |

---

## 2. Local Setup and Prerequisites 🛠️

To deploy and run this pipeline, you must have **Docker** and **Docker Compose** installed.

### 2.1. Project Structure

Your project folder (`airflow-postgres/`) should be structured as follows:
```bash
airflow-postgres/
├── dags/
  └── subreddit_sentiment_dag.py
├── docker-compose.yml
├── .env
└── requirements.txt
```

### 2.2. Environment Configuration (`.env`)

The `.env` file is used to configure both the Docker container user ID and the **Reddit API credentials** which are securely injected into the Airflow containers.

```bash
# .env file content
AIRFLOW_UID=50000
REDDIT_CLIENT_ID='7tDkBK9y7FX7DRh8wIuhtg'
REDDIT_CLIENT_SECRET='ZOqfHMG1Me2jRud8F_i2d_FRRbW9uA'
REDDIT_USER_AGENT='reddit-sentiment-analysis-script-by egoj'
```

### 2.3. Python Dependencies (requirements.txt)
These libraries are required for scraping, sentiment analysis, and database connectivity. They are installed on the Airflow containers during startup via _PIP_ADDITIONAL_REQUIREMENTS in docker-compose.yml.

```Plaintext
# requirements.txt
pandas
praw
nltk
psycopg2-binary
apache-airflow-providers-postgres
```

### 2.4. Airflow Connection Setup
The DAG uses the Airflow Connections feature to manage credentials safely. After starting the containers (see Step 2.5), you must configure a connection in the Airflow UI:

1. Navigate to Admin -> Connections.
2. Create a new connection with the following details:
   * Conn Id: `reddit_api_conn`
   * Conn Type: `Generic`
   * Password: `[Paste REDDIT_CLIENT_ID here]` (This maps to `conn.password` in the DAG)
   * Extra:
```
{
  "client_secret": "[Paste REDDIT_CLIENT_SECRET here]",
  "user_agent": "[Paste REDDIT_USER_AGENT here]"
}
```

### 2.5. Deployment Steps
1. Navigate to your project root in the terminal.
2. Start the containers with the command: `docker-compose up -d`
3. Access the Airflow UI at `http://localhost:8080`
4. Access the PostgreSQL database on port `5433` (`5433:5432` mapping in `docker-compose.yaml`)

## 3. ETL Logic: Update and Insert
The loading task uses a sophisticated two-step process: COPY to a staging table, then UPSERT to the final table.

### 3.1. Database Tables
The pipeline dynamically creates two tables using `prepare_table` task:
1. `sentiment_results`: The final, permanent data table.
2. `staging_sentiment_results`: A temporary table cleared and reloaded for every DAG run, used as the source for the update and insert.

### 3.2. PostgreSQL
The loading logic is executed by the `load_data_to_postgres` Python function using the `PostgresHook` and the PostgreSQL `ON CONFLICT` clause.
* Conflict Key: The unique `post_id` is the conflict target, ensuring only one record exists per Reddit post.
* Action on Conflict: The existing record is updated (`DO UPDATE SET`) with the latest sentiment scores, body, and the new `scrape_timestamp`.
```SQL
INSERT INTO sentiment_results (...)
SELECT ... FROM staging_sentiment_results
ON CONFLICT (post_id) DO UPDATE SET
    title = EXCLUDED.title,
    body = EXCLUDED.body,
    ...
    scrape_timestamp = EXCLUDED.scrape_timestamp;
```

## 4. Database Schema Reference
The final, clean data is stored in the `sentiment_results` table.
| Column Name | Data Type | Constraint | Description |
| :--- | :--- | :--- | :--- |
| **`post_id`** | `VARCHAR(20)` | `PRIMARY KEY` | Unique identifier for the Reddit submission. Used as the conflict target for UPSERT. |
| `subreddit` | `VARCHAR(50)` | `NOT NULL` | The subreddit name (e.g., 'mlb'). |
| `title` | `VARCHAR(300)` | | The title of the Reddit post. |
| `body` | `TEXT` | | The self-text content of the post. |
| `reddit_submission_timestamp` | `TIMESTAMP` | | The time the post was originally created on Reddit (UTC). |
| `compound_score` | `NUMERIC` | | **VADER Sentiment:** The normalized, overall score ($[-1.0, +1.0]$). Closer to 1 is positive, closer to -1 is negative. |
| `pos_score` | `NUMERIC` | | **VADER Sentiment:** The fraction of text that is positive. |
| `neg_score` | `NUMERIC` | | **VADER Sentiment:** The fraction of text that is negative. |
| `neu_score` | `NUMERIC` | | **VADER Sentiment:** The fraction of text that is neutral. |
| `scrape_timestamp` | `TIMESTAMP` | | The time this row was last inserted or updated by the DAG. |
