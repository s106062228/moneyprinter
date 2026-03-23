#!/bin/bash
set -euo pipefail

# Script to generate & Upload a video to YT Shorts

# Check which interpreter to use (python)
if command -v python3 &>/dev/null; then
  PYTHON=python3
else
  PYTHON=python
fi

# Read .mp/youtube.json file, loop through accounts array, get each id
youtube_ids=$("$PYTHON" -c "import json; print('\n'.join([account['id'] for account in json.load(open('.mp/youtube.json'))['accounts']]))")

echo "What account do you want to upload the video to?"

# Print the ids
echo "$youtube_ids"

# Ask for the id
read -rp "Enter the id: " id

# Validate input — only allow UUID-like strings (alphanumeric + hyphens)
if [[ ! "$id" =~ ^[a-zA-Z0-9-]+$ ]]; then
  echo "Invalid ID format."
  exit 1
fi

# Check if the id is in the list
if echo "$youtube_ids" | grep -qx "$id"; then
  echo "ID found"
else
  echo "ID not found"
  exit 1
fi

# Run python script
"$PYTHON" src/cron.py youtube "$id"
