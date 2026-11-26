@echo off
REM Lance le serveur Django du Gestionnaire de societe
cd /d "%~dp0"
call envnew\Scripts\activate.bat
REM Installe les paquets manquants (ex. openpyxl pour l'export Excel) - rapide si deja installes
python -m pip install -q -r requirements.txt --disable-pip-version-check
python manage.py migrate --noinput
start "" http://127.0.0.1:8000/
python manage.py runserver 127.0.0.1:8000
pause
