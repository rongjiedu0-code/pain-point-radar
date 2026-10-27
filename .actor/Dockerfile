FROM apify/actor-python:3.11
WORKDIR /usr/src/app
COPY apify-actors/startup-pain-point-radar-ppe/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY apify-actors/startup-pain-point-radar-ppe/ ./
CMD ["python3", "-m", "src"]
