#!/bin/bash
# Threads Growth Skill — Setup Helper
# This script is invoked by Hermes during first-time setup.
# It tests cookie login and confirms your Threads user ID.

SESSION="hermes_browser"

echo "=== Threads Growth Skill Setup ==="
echo ""
echo "Testing login with provided cookies..."

agent-browser --session $SESSION open 'https://www.threads.com' 2>&1
agent-browser --session $SESSION eval "document.cookie='sessionid=${THREADS_SESSION_ID}; path=/; domain=.threads.com; secure'" 2>&1
agent-browser --session $SESSION eval "document.cookie='ds_user_id=${THREADS_USER_ID}; path=/; domain=.threads.com'" 2>&1
agent-browser --session $SESSION eval "document.cookie='csrftoken=${THREADS_CSRF_TOKEN}; path=/; domain=.threads.com'" 2>&1
agent-browser --session $SESSION eval "document.cookie='mid=${THREADS_MID}; path=/; domain=.threads.com'" 2>&1

agent-browser --session $SESSION open "https://www.threads.com/@${THREADS_HANDLE}" 2>&1
sleep 3

TITLE=$(agent-browser --session $SESSION eval "document.title" 2>&1)

if echo "$TITLE" | grep -qE '^\([0-9]+\)'; then
  echo "✅ Login successful!"
  echo "Account: ${THREADS_HANDLE}"
  echo ""
  echo "Next: Hermes will scrape your Insights and create winning-formats.md"
else
  echo "❌ Login failed. Please check:"
  echo "  1. You exported cookies while logged into threads.com"
  echo "  2. The export format was 'Netscape'"
  echo "  3. The session hasn't expired"
  exit 1
fi
