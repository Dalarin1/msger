#!/bin/bash
docker build -t msger --cache-from msger .

docker stop msger 2>/dev/null
docker rm msger 2>/dev/null

docker run -d -p 80:80 \
    -v "$(pwd)/global_chat:/msger/global_chat" \
    -v "$(pwd)/personal_chats:/msger/personal_chats" \
    -v "$(pwd)/database:/msger/database" \
    --name msger \
    msger