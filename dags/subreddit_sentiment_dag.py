from __future__ import annotations
import pendulum
import pandas as pd
import praw
import time
import logging 
from io import StringIO

from airflow.models.dag import DAG
from airflow.providers.standard.operators.python import PythonOperator
from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator
from airflow.sdk.bases.hook import BaseHook 
from airflow.providers.postgres.hooks.postgres import PostgresHook 
from nltk.sentiment.vader import SentimentIntensityAnalyzer

# Set up logging
log = logging.getLogger(__name__)
analyzer = SentimentIntensityAnalyzer()

# --- CONFIGURATION ---
POSTGRES_CONN_ID = "postgres_default"
REDDIT_CONN_ID = "reddit_api_conn"
SUBREDDIT_NAME = "mlb" # The subreddit where the scraping will happen
SCRAPE_LIMIT = 1000 
BATCH_SIZE = 1000 


# Create Table
CREATE_TABLE_SQL = """
-- 1. Final Table (Remains permanent)
CREATE TABLE IF NOT EXISTS sentiment_results (
    post_id VARCHAR(20) PRIMARY KEY,
    subreddit VARCHAR(50) NOT NULL,
    title VARCHAR(300),
    body TEXT,
    reddit_submission_timestamp TIMESTAMP,
    compound_score NUMERIC,
    pos_score NUMERIC,
    neg_score NUMERIC,
    neu_score NUMERIC,
    scrape_timestamp TIMESTAMP DEFAULT NOW()
);

-- 2. Staging Table
CREATE TABLE IF NOT EXISTS staging_sentiment_results (
    post_id VARCHAR(20),
    subreddit VARCHAR(50),
    title VARCHAR(300),
    body TEXT,
    reddit_submission_timestamp TIMESTAMP,
    compound_score NUMERIC,
    pos_score NUMERIC,
    neg_score NUMERIC,
    neu_score NUMERIC,
    scrape_timestamp TIMESTAMP
);
"""
DROP_STAGING_TABLE_SQL = "DROP TABLE IF EXISTS staging_sentiment_results;"


# --- ETL ---

def extract_transform_data(reddit_conn_id, subreddit_name, scrape_limit, batch_size, **context):
    """
    Extracts, transforms, and pushes the resulting DataFrame as a CSV string to XCom.
    Now handles scrape_limit > 1000 by batching requests.
    """
    log = logging.getLogger(__name__)
    ti = context['ti']

    try:
        scrape_limit = int(scrape_limit)
    except ValueError:
        log.error(f"Invalid scrape_limit: {scrape_limit}. Defaulting to 1000.")
        scrape_limit = 1000
    
    # 1. Retrieve Credentials from Airflow Connection
    conn = BaseHook.get_connection(reddit_conn_id)
    client_id = conn.password
    extra = conn.extra_dejson 
    client_secret = extra.get("client_secret")
    user_agent = extra.get("user_agent")

    # 2. Initialize PRAW
    reddit = praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent
    )

    log.info(f"Starting scrape: Target {scrape_limit} newest posts from r/{subreddit_name}.")
    
    all_data = []
    posts_collected = 0
    after_id = None # Used for pagination
    current_scrape_time = pendulum.now()

    while posts_collected < scrape_limit:
        
        remaining_to_fetch = scrape_limit - posts_collected
        current_batch_size = min(remaining_to_fetch, batch_size)

        log.info(f"Fetching batch. Collected: {posts_collected}. Requesting: {current_batch_size}. After: {after_id}")
        
        try:
            params = {'after': after_id} if after_id else {}
            
            submissions = list(reddit.subreddit(subreddit_name).new(
                limit=current_batch_size,
                params=params
            ))
        except Exception as e:
            log.error(f"Error during PRAW request: {e}. Stopping scrape.")
            break 

        if not submissions:
            log.warning("PRAW returned no more submissions. End of subreddit history reached.")
            break 

        # Process the batch of submissions
        for submission in submissions:
            text_to_analyze = submission.title + " " + (submission.selftext or "")
            scores = analyzer.polarity_scores(text_to_analyze)
            
            all_data.append({
                'post_id': submission.id,
                'subreddit': submission.subreddit.display_name,
                'title': submission.title,
                'body': submission.selftext, 
                'reddit_submission_timestamp': pd.to_datetime(submission.created_utc, unit='s'),
                'compound_score': scores['compound'],
                'pos_score': scores['pos'],
                'neg_score': scores['neg'],
                'neu_score': scores['neu'],
                'scrape_timestamp': current_scrape_time 
            })
            posts_collected += 1
        
        # Set the 'after_id' for the next loop iteration
        after_id = submissions[-1].fullname
        log.info(f"Batch completed ({len(submissions)} posts). Total collected: {posts_collected}.")

        if posts_collected < scrape_limit:
        # Wait for 1-2 seconds between requests to stay under the rate limit
            log.info("Pausing for 1.5 seconds to respect Reddit API rate limits...")
            time.sleep(1.5)
    
    
    df = pd.DataFrame(all_data)
    
    if df.empty:
        log.warning("No data scraped. Pushing empty string to XCom.")
        ti.xcom_push(key='sentiment_data_csv', value="")
        return 0
    
    log.info(f"Successfully scraped and analyzed {len(df)} posts.")

    csv_buffer = StringIO()
    
    columns = [
        'post_id', 'subreddit', 'title', 'body', 
        'reddit_submission_timestamp', 'compound_score', 
        'pos_score', 'neg_score', 'neu_score', 'scrape_timestamp'
    ]
    
    df.to_csv(csv_buffer, index=False, header=False, columns=columns)
    
    ti.xcom_push(key='sentiment_data_csv', value=csv_buffer.getvalue())
    
    return len(df)


def load_data_to_postgres(postgres_conn_id, **context):
    """
    Performs an UPSERT:
    1. COPYs data into a temporary staging table using the direct psycopg2 cursor.
    2. MERGEs data from staging to the final table using ON CONFLICT (UPSERT).
    """
    
    log = logging.getLogger(__name__)
    ti = context['ti']
    pg_hook = PostgresHook(postgres_conn_id)
    
    csv_string = ti.xcom_pull(task_ids='extract_and_transform', key='sentiment_data_csv')
    
    if not csv_string:
        log.warning("No data received from upstream task. Skipping load.")
        return "Load skipped."

    csv_buffer = StringIO(csv_string)
    
    staging_table = "staging_sentiment_results"
    final_table = "sentiment_results"
    
    copy_columns = [
        'post_id', 'subreddit', 'title', 'body', 
        'reddit_submission_timestamp', 'compound_score', 
        'pos_score', 'neg_score', 'neu_score', 'scrape_timestamp'
    ]
    
    sql_copy_command = f"""
        COPY {staging_table} ({', '.join(copy_columns)}) 
        FROM STDIN WITH (FORMAT CSV)
    """

    log.info(f"Connecting to database and executing bulk load into {staging_table}...")
    conn = pg_hook.get_conn()
    
    try:
        with conn.cursor() as cursor:
            
            # 1. Clear the staging table
            log.info("Truncating staging table.")
            cursor.execute(f"TRUNCATE TABLE {staging_table};") 

            # 2. Copy data from the buffer to the staging table
            log.info("Executing copy with cursor.copy_expert (in-memory data)...")
            cursor.copy_expert(sql=sql_copy_command, file=csv_buffer)
            
            # 3. Merge Staging Data into Final Table
            log.info(f"Merging data from {staging_table} to {final_table} via UPSERT...")
            upsert_sql = f"""
            INSERT INTO {final_table} ({', '.join(copy_columns)})
            SELECT {', '.join(copy_columns)} FROM {staging_table}
            ON CONFLICT (post_id) DO UPDATE SET
                title = EXCLUDED.title,
                body = EXCLUDED.body,
                compound_score = EXCLUDED.compound_score,
                pos_score = EXCLUDED.pos_score,
                neg_score = EXCLUDED.neg_score,
                neu_score = EXCLUDED.neu_score,
                scrape_timestamp = EXCLUDED.scrape_timestamp;
            """
            cursor.execute(upsert_sql)

        log.info("Committing transaction...")
        conn.commit()

    except Exception as e:
        log.error(f"Error during bulk load or UPSERT: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()
    
    rows_processed = len(csv_string.splitlines())
    log.info(f"Successfully processed {rows_processed} rows via UPSERT.")
    
    return f"Load complete. Rows processed: {rows_processed}"


# --- DAG ---

with DAG(
    dag_id="subreddit_sentiment_analysis",
    start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
    #schedule="0 0,4,8,12,16,20 * * *", 
    schedule=None,
    catchup=False,
    tags=["etl", "reddit", "sentiment", "incremental"],
    doc_md=__doc__,
) as dag:

    # Task 1: Prepare the destination and staging tables
    prepare_table = SQLExecuteQueryOperator(
        task_id="create_tables",
        conn_id=POSTGRES_CONN_ID,
        sql=CREATE_TABLE_SQL, 
    )

    # Task 2: Extract, Transform, and prepare for loading
    etl_task = PythonOperator(
        task_id="extract_and_transform",
        python_callable=extract_transform_data,
        op_kwargs={
            "reddit_conn_id": REDDIT_CONN_ID,
            "subreddit_name": SUBREDDIT_NAME,
            "scrape_limit": SCRAPE_LIMIT,
            "batch_size": BATCH_SIZE, # <-- Pass the batch size to the function
        },
    )

    # Task 3: Load the processed data into the database using UPSERT
    load_task = PythonOperator(
        task_id="load_data_to_postgres",
        python_callable=load_data_to_postgres,
        op_kwargs={
            "postgres_conn_id": POSTGRES_CONN_ID,
        },
    )

    # --- Define Task Dependencies ---
    prepare_table >> etl_task >> load_task
