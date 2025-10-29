FROM apache/airflow:3.1.0

LABEL maintainer="subreddit-scraper-sentiment-analysis"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
ENV NLTK_DATA /home/airflow/nltk_data
RUN python -c "import nltk; nltk.download('vader_lexicon', download_dir='/home/airflow/nltk_data')"
