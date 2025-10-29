# Subreddit Sentiment Analysis: Personal ETL Project

This project deploys an Airflow-orchestrated Data Engineering pipeline designed to analyze the overall sentiment within a specific Reddit subreddit. The pipeline utilizes the PRAW library for scraping recent posts, performs VADER sentiment analysis to categorize text, and loads the structured results into a PostgreSQL database. It uses an update and insert logic for maintaining data integrity and preventing duplicate records. The pipeline is intentionally scoped to focus on retrieving only the most recent posts ($\sim 1,000$ per run) to demonstrate a functional ETL flow. (Reddit imposed a maximum of 1000 posts for this type of query)

The primary goal of this project was to apply and reinforce core concepts learned in my online courses provided by a scholarship from DataCamp (Python, SQL, Airflow, and Docker). The reason why I used a local PostgreSQL database, Airflow, and Docker as this project's components was because these are the free and available alternative of those used by companies in the tech industry. While the foundational scripts were initially generated with LLM assistance, final pipeline is the result of my direct effort in debugging, connecting components, and revising the logic to ensure execution.

# Key Learnings & Takeaways

* Integration of Technologies (Docker, Airflow, PRAW): A significant challenge I faced was trying to integrate these tools, from setting up the Python environment via Docker to securing a connection between the Airflow environment and the API's.
* Scope Management: Model Selection: The core focus of this project was pipeline integrity and data flow, not model optimization. I chose the VADER model because it provided quick, readable sentiment scores which perfectly served the goal of demonstrating a complete ETL process. I intentionally did not invest time in researching more complex models to keep the project focused on the core data engineering challenges and producing a clean, structured output.
* Leveraging LLMs for Workflow Efficiency: Using an LLM for initial code generation significantly reduced development time. This allowed me to concentrate on debugging challenges across Airflow, Postgres, and Python tasks that would otherwise have required months of dedicated documentation research for cross-platform implementation.

## 1. Project Architecture and DAG Overview 

| Component | Purpose | Technology | Key Feature |
| :--- | :--- | :--- | :--- |
| **`subreddit_sentiment_analysis`** | **The ETL Pipeline.** Orchestrates the entire data flow. | Apache Airflow | Manual Trigger (`schedule=None`) |
| **Data Extraction** | Scrapes the "new" posts from the Reddit API. | PRAW via Airflow `BaseHook` | Retrieves the latest 1000 posts |
| **Data Transformation** | Calculates four distinct sentiment scores. | VADER (nltk) | Provides `compound_score` for normalized overall sentiment. |
| **Data Loading** | Writes data automatically to the final table. | PostgreSQL + `psycopg2` | Implements **`ON CONFLICT (post_id) DO UPDATE`**. |

---

## 2. Local Setup and Prerequisites 

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
REDDIT_CLIENT_ID='[YOUR_REDDIT_CLIENT_ID]'
REDDIT_CLIENT_SECRET='[YOUR_REDDIT_CLIENT_SECRET]'
REDDIT_USER_AGENT='[A_DESCRIPTIVE_USER_AGENT]'
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
The loading task uses a two-step process: COPY to a staging table, then update and insert to the final table.

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
