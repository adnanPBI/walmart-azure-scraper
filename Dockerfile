# This is a pinned-vendor Playwright browser image. Update and re-run tests regularly.
FROM mcr.microsoft.com/playwright/python:v1.56.0-noble
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /opt/scraper
COPY pyproject.toml README.md /opt/scraper/
COPY walmart_azure/ /opt/scraper/walmart_azure/
RUN pip install --no-cache-dir .
# Only public review configuration goes into the build. Never bundle local
# browser/session state, account keys, or an operator-edited private stores.yaml.
COPY config/categories.csv /opt/scraper/config/categories.csv
COPY config/stores.azure.yaml /opt/scraper/config/stores.yaml
USER pwuser
ENTRYPOINT ["walmart-crawl"]
# Safe diagnostic default. Does not publish a product dataset.
CMD ["probe", "--store", "3891", "--categories", "/opt/scraper/config/categories.csv", "--stores", "/opt/scraper/config/stores.yaml", "--max-requests", "8", "--max-seconds", "300"]
