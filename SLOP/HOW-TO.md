Запустить на локалхосте:
python main.py

Запустить на серваке с доменом:
 - Шуруй в docker-compose.certbot.yml
 - Там меняешь:
 - - --email your@email.com на --email <твой мыло адрес>
 - - -d yourdomain.com на -d <твой домен>
 - запускаешь через `docker compose -f docker-compose.certbot.yml up -d`