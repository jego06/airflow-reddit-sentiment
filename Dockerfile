FROM apache/airflow:3.1.0

LABEL maintainer="subreddit-scraper-sentiment-analysis"

# 1. Install all necessary python packages in one layer
# This should contain pandas, psycopg2-binary, praw, nltk, and the postgres provider.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. Download NLTK data to a persistent, known location
ENV NLTK_DATA /home/airflow/nltk_data
RUN python -c "import nltk; nltk.download('vader_lexicon', download_dir='/home/airflow/nltk_data')"