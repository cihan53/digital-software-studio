#!/usr/bin/env bash
# ==============================================================================
#  Digital Software Studio — 1-Tık Kurulum ve Ortam Hazırlayıcı (Setup Script)
# ==============================================================================

set -euo pipefail
cd "$(dirname "$0")"

BOLD='\033[1m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}╔══════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║${NC}   🤖 ${BOLD}Digital Software Studio — Kurulum ve Hazırlık Sihirbazı${NC}          ${CYAN}║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════════════════╝${NC}"
echo

# 1. Python 3 Kontrolü
echo -e "${BOLD}1. Python Ortamı Denetleniyor...${NC}"
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}✗ Python 3 bulunamadı. Lütfen Python 3.10 veya üzerini kurunuz.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python 3 mevcut: $(python3 --version)${NC}"

# 2. Virtualenv Kurulumu
echo -e "\n${BOLD}2. Sanal Ortam (.venv) Yapılandırılıyor...${NC}"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo -e "${GREEN}✓ .venv sanal ortamı başarıyla oluşturuldu.${NC}"
else
    echo -e "${GREEN}✓ .venv sanal ortamı zaten hazır.${NC}"
fi

# 3. Antigravity CLI (agy) Kontrolü
echo -e "\n${BOLD}3. Antigravity CLI (agy) Denetleniyor...${NC}"
AGY_BIN="$(command -v agy 2>/dev/null || true)"
if [ -z "$AGY_BIN" ] && [ -x "$HOME/.local/bin/agy" ]; then
    AGY_BIN="$HOME/.local/bin/agy"
fi

if [ -n "$AGY_BIN" ]; then
    echo -e "${GREEN}✓ Antigravity CLI bulundu: $AGY_BIN${NC}"
else
    echo -e "${YELLOW}! agy CLI bulunamadı.${NC}"
    echo -e "${DIM}  Antigravity CLI kurulu değilse model çağrıları için kurulması önerilir.${NC}"
fi

# 3b. Devin CLI (alternatif backend) Kontrolü
echo -e "\n${BOLD}3b. Devin CLI (opsiyonel backend) Denetleniyor...${NC}"
DEVIN_BIN="$(command -v devin 2>/dev/null || true)"
if [ -z "$DEVIN_BIN" ] && [ -x "$HOME/.local/bin/devin" ]; then
    DEVIN_BIN="$HOME/.local/bin/devin"
fi

if [ -n "$DEVIN_BIN" ]; then
    echo -e "${GREEN}✓ Devin CLI bulundu: $DEVIN_BIN${NC}"
    echo -e "${DIM}  STUDIO_BACKEND=devin ile tüm stüdyo Devin AI üzerinden çalıştırılabilir.${NC}"
else
    echo -e "${YELLOW}! devin CLI bulunamadı (opsiyonel).${NC}"
    echo -e "${DIM}  Devin AI backend'ini kullanmak için Devin CLI/Desktop kurulmalıdır.${NC}"
fi

# 4. Proje İsterleri Dosyası Kontrolü
echo -e "\n${BOLD}4. Proje Kapsamı Dosyası Denetleniyor...${NC}"
if [ ! -f "proje_kapsami.md" ]; then
    if [ -f "proje_kapsami.template.md" ]; then
        cp proje_kapsami.template.md proje_kapsami.md
        echo -e "${GREEN}✓ proje_kapsami.template.md dosyasından yeni proje_kapsami.md oluşturuldu.${NC}"
    fi
else
    echo -e "${GREEN}✓ proje_kapsami.md mevcut.${NC}"
fi

# Çalıştırma izinleri
chmod +x basla.sh musteri.sh setup.sh studio_schedule.sh 2>/dev/null || true

echo -e "\n${CYAN}══════════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}✓ KURULUM TAMAMLANDI! Stüdyonuz çalışmaya hazır.${NC}"
echo -e "${CYAN}══════════════════════════════════════════════════════════════════════${NC}"
echo -e "\n${BOLD}Nasıl Başlatılır?${NC}"
echo -e "  1. Projenizi tarif edin:  ${CYAN}nano proje_kapsami.md${NC}"
echo -e "  2. Stüdyoyu başlatın:     ${CYAN}./basla.sh${NC}"
echo -e "  3. İlerlemeyi izleyin:    ${CYAN}./basla.sh --izle${NC}"
echo -e "  4. Müşteri masasını açın: ${CYAN}./musteri.sh${NC}"
echo
