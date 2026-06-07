call docker build -t msger --cache-from msger .

call docker stop msger 2>nul
call docker rm msger 2>nul

call docker run -d -p 80:80 ^
    -v "%cd%\global_chat:/msger/global_chat" ^
    -v "%cd%\personal_chats:/msger/personal_chats" ^
    -v "%cd%\database:/msger/database" ^
    --name msger ^
    msger