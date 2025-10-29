from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook
from datetime import datetime
import pandas as pd
import logging
import io
import os # <-- Added 'os' for file path/directory management


# --- Configuration ---
POSTGRES_CONN_ID = "postgres_default"
TABLE_NAME = "processed_data"
# Paths inside the Airflow container
INPUT_FILE_PATH = "/opt/airflow/data_input/sample_data.csv"
OUTPUT_DIR = "/opt/airflow/data_output"
OUTPUT_FILE_PATH = os.path.join(OUTPUT_DIR, "processed_data.csv") # <-- Defined the output path


# --- Python Functions ---
def process_and_load_data():
    """
    Reads a CSV, processes it, saves a copy to the output folder, 
    and then efficiently loads the data into Postgres via COPY command.
    """
    hook = PostgresHook(postgres_conn_id=POSTGRES_CONN_ID)
    
    try:
        logging.info(f"Reading CSV from: {INPUT_FILE_PATH}")
        df = pd.read_csv(INPUT_FILE_PATH)
        logging.info(f"Successfully read {len(df)} rows. Columns: {df.columns.tolist()}")

        # Ensure output directory exists
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        # Save the processed data to CSV including header
        logging.info(f"Saving processed data to: {OUTPUT_FILE_PATH}")
        df.to_csv(OUTPUT_FILE_PATH, index=False)  # keep header

        # Prepare SQL COPY command with HEADER
        sql_copy = f"COPY {TABLE_NAME} (id, name, value) FROM STDIN WITH CSV HEADER"

        # Open the saved CSV and stream it to Postgres
        logging.info(f"Loading data into {TABLE_NAME} using file: {OUTPUT_FILE_PATH}")
        with open(OUTPUT_FILE_PATH, "r") as f:
            hook.copy_expert(sql=sql_copy, filename=f.name)

        logging.info("Data loaded successfully!")

    except FileNotFoundError:
        logging.error(f"Input file not found at: {INPUT_FILE_PATH}")
        raise
    except Exception as e:
        logging.error(f"An error occurred: {e}")
        raise

# --- DAG Definition ---
with DAG(
    dag_id="csv_to_postgres_loader_with_output", # Updated ID to reflect the change
    start_date=datetime(2025, 1, 1),
    schedule=None,
    catchup=False,
    tags=["data_pipeline", "python", "postgres", "modern"],
) as dag:

    # Task 1: Create and truncate the table using the modern SQLExecuteQueryOperator
    create_table = SQLExecuteQueryOperator(
        task_id="create_and_truncate_table",
        conn_id=POSTGRES_CONN_ID, # Standardized parameter name
        sql=f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                id INT PRIMARY KEY,
                name VARCHAR(255),
                value INT
            );
            -- Clear the table before running to ensure a clean load
            TRUNCATE TABLE {TABLE_NAME};
        """,
    )

    # Task 2: Run the Python function to process, save, and load the data
    process_and_load_task = PythonOperator(
        task_id="process_save_and_load_csv",
        python_callable=process_and_load_data,
    )
    
    # Define the task dependencies
    create_table >> process_and_load_task