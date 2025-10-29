# Reddit Sentiment Analysis ETL Pipeline

This project is an **Airflow-orchestrated Data Engineering pipeline** designed to ingest posts from Reddit, perform sentiment analysis using VADER, and load the processed results into a PostgreSQL database using a robust **UPSERT (Update or Insert)** mechanism.

The pipeline is split into two separate DAGs to efficiently handle distinct data requirements: live monitoring and deep historical scraping.

## 1. Project Architecture and DAG Overview 

The system uses Docker Compose to manage Airflow, PostgreSQL, and their dependencies.

| DAG Name | Purpose | Source API | Schedule | Key Limitation |
| :--- | :--- | :--- | :--- | :--- |
| **`subreddit_sentiment_analysis`** | **Live Monitoring (Shallow).** Scrapes the newest $\sim 1,000$ posts per run to capture fresh, real-time sentiment. | Reddit Official API (PRAW) | Manual Trigger Only | Limited to the top $\sim 1,000$ "new" posts by Reddit API design. |
| **`subreddit_history_psaw`** | **Historical Archive (Deep).** Scrapes historical data beyond the live API's $\sim 1,000$ post depth. | Pushshift API (PSA W) | Manual Trigger Only | Requires external API endpoint; designed for large-scale historical recovery. |

---

## 2. Local Setup and Prerequisites 🛠️

To successfully deploy and run this pipeline, you must have **Docker** and **Docker Compose** installed.

### 2.1. Project Structure

Ensure your file structure is organized as follows:
