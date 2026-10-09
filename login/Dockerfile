# Trumf and Coop login images use Playwright; Rema uses a manual OAuth callback flow.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN pip install --no-cache-dir "playwright==1.47.0"
COPY *.py /login/
WORKDIR /login
ENTRYPOINT ["python"]
