#!/bin/bash
set -e

echo "======================================"
echo " Museum Audio Guide — Server Setup"
echo "======================================"

# 1. Tizimni yangilash
echo "[1/7] Tizim yangilanmoqda..."
apt-get update -qq && apt-get upgrade -y -qq

# 2. Kerakli paketlar
echo "[2/7] Python, nginx, git o'rnatilmoqda..."
apt-get install -y -qq python3 python3-pip python3-venv nginx git

# 3. Kodni yuklash
echo "[3/7] GitHub dan kod yuklanmoqda..."
mkdir -p /var/www
if [ -d "/var/www/museum-guide" ]; then
  cd /var/www/museum-guide && git pull
else
  git clone https://github.com/ewboyeff/state-of-museum.git /var/www/museum-guide
fi

# 4. Python muhiti
echo "[4/7] Python virtual environment sozlanmoqda..."
cd /var/www/museum-guide/backend
python3 -m venv venv
source venv/bin/activate
pip install -q -r requirements.txt

# 5. .env fayli
echo "[5/7] .env fayli yaratilmoqda..."
if [ ! -f "/var/www/museum-guide/backend/.env" ]; then
  cp /var/www/museum-guide/backend/.env.example /var/www/museum-guide/backend/.env
  echo ""
  echo ">>> .env faylini to'ldiring:"
  echo "    nano /var/www/museum-guide/backend/.env"
  echo ""
fi

# 6. Nginx
echo "[6/7] Nginx sozlanmoqda..."
cp /var/www/museum-guide/deploy/nginx.conf /etc/nginx/sites-available/museum-guide
ln -sf /etc/nginx/sites-available/museum-guide /etc/nginx/sites-enabled/museum-guide
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

# 7. Systemd service
echo "[7/7] Servis sozlanmoqda..."
cat > /etc/systemd/system/museum-guide.service << 'EOF'
[Unit]
Description=Museum Audio Guide Backend
After=network.target

[Service]
User=root
WorkingDirectory=/var/www/museum-guide/backend
ExecStart=/var/www/museum-guide/backend/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=5
EnvironmentFile=/var/www/museum-guide/backend/.env

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable museum-guide

echo ""
echo "======================================"
echo " Muvaffaqiyatli o'rnatildi!"
echo "======================================"
echo ""
echo "Keyingi qadam — .env faylini to'ldiring:"
echo "  nano /var/www/museum-guide/backend/.env"
echo ""
echo "Keyin serverni ishga tushiring:"
echo "  systemctl start museum-guide"
echo "  systemctl status museum-guide"
echo ""
