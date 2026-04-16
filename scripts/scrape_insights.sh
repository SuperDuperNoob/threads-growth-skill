#!/bin/bash
# Threads Insights Scraper
# Usage: Called by Hermes Agent — not meant to run standalone
# Requires: agent-browser installed, SESSION_ID and CSRF_TOKEN env vars set

SESSION="hermes_browser"
SESSION_ID="${THREADS_SESSION_ID}"
CSRF="${THREADS_CSRF_TOKEN}"
USER_ID="${THREADS_USER_ID}"
MID="${THREADS_MID}"

if [ -z "$SESSION_ID" ] || [ -z "$USER_ID" ]; then
  echo "ERROR: THREADS_SESSION_ID and THREADS_USER_ID must be set"
  echo "Run the setup flow first: tell Hermes 'set up my threads growth skill'"
  exit 1
fi

echo "Injecting cookies..."
agent-browser --session $SESSION open 'https://www.threads.com' 2>&1
agent-browser --session $SESSION eval "document.cookie='sessionid=${SESSION_ID}; path=/; domain=.threads.com; secure'" 2>&1
agent-browser --session $SESSION eval "document.cookie='ds_user_id=${USER_ID}; path=/; domain=.threads.com'" 2>&1
agent-browser --session $SESSION eval "document.cookie='csrftoken=${CSRF}; path=/; domain=.threads.com'" 2>&1
agent-browser --session $SESSION eval "document.cookie='mid=${MID}; path=/; domain=.threads.com'" 2>&1

echo "Navigating to Insights..."
agent-browser --session $SESSION open 'https://www.threads.com/insights/posts?days=30' 2>&1
sleep 3

TITLE=$(agent-browser --session $SESSION eval "document.title" 2>&1)
if echo "$TITLE" | grep -qE '^\([0-9]+\)'; then
  echo "✅ Logged in successfully"
else
  echo "❌ Login failed — cookies may be expired"
  echo "Please export fresh cookies from threads.com and update your setup"
  exit 2
fi

echo "Scraping top posts..."
agent-browser --session $SESSION snapshot 2>&1
