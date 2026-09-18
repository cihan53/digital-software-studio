#!/usr/bin/env bash
# ==============================================================================
#  Digital Software Studio — Müşteri Denetim & Geri Bildirim Masası
#  Proje Sahibi / Denetçi ile Studio Ekibi Arasındaki Köprü
# ==============================================================================

set -eo pipefail
cd "$(dirname "$0")" || exit 1

PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"

# Renkler ve Biçimlendirme
BOLD='\033[1m'
DIM='\033[2m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

header() {
  clear 2>/dev/null || true
  echo -e "${CYAN}╔══════════════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${CYAN}║${NC}   ⚡ ${BOLD}Digital Software Studio — Müşteri Denetim & Geri Bildirim Masası${NC}   ${CYAN}║${NC}"
  echo -e "${CYAN}║${NC}   ${DIM}Rol: Proje Sahibi / Ürün Denetçisi${NC}                                 ${CYAN}║${NC}"
  echo -e "${CYAN}╚══════════════════════════════════════════════════════════════════════╝${NC}"
  echo
}

yeni_bildirim_formu() {
  header
  echo -e "${BOLD}📝 Yeni İstek veya Hata Bildirimi${NC}"
  echo -e "${DIM}Gördüğünüz eksiklik veya hatayı yazın; Studio Yetkilisi bunu ekibiyle planlayacak.${NC}"
  echo "────────────────────────────────────────────────────────────────────────"
  
  echo -e "\n${BOLD}1. Bildirim Türü:${NC}"
  echo "  1) HATA (Bug / Çalışmayan veya hatalı işlev)"
  echo "  2) ISTEK (Yeni Özellik veya geliştirme)"
  echo "  3) UX (Tasarım, mobil görünüm veya kullanıcı deneyimi)"
  echo "  4) VERI (Eksik veya hatalı istasyon verisi)"
  read -r -p "Seçiminiz [1-4] (Varsayılan: 1): " tur_secim
  case "$tur_secim" in
    2) TUR="ISTEK" ;;
    3) TUR="UX" ;;
    4) TUR="VERI" ;;
    *) TUR="HATA" ;;
  esac

  echo -e "\n${BOLD}2. Öncelik Derecesi:${NC}"
  echo "  1) NORMAL (Olağan düzeltme / geliştirme)"
  echo "  2) YUKSEK (Kullanımı aksatan önemli eksiklik)"
  echo "  3) KRITIK (Sistemi kilitleyen / acil müdahale gereken)"
  read -r -p "Seçiminiz [1-3] (Varsayılan: 1): " onc_secim
  case "$onc_secim" in
    2) ONCELIK="YUKSEK" ;;
    3) ONCELIK="KRITIK" ;;
    *) ONCELIK="NORMAL" ;;
  esac

  echo -e "\n${BOLD}3. İlgili Sayfa veya URL:${NC} (Örn: /, /[operator], İstasyon Detay Paneli)"
  read -r -p "Sayfa [/]: " SAYFA
  [ -z "$SAYFA" ] && SAYFA="/"

  echo -e "\n${BOLD}4. Kısa Başlık:${NC}"
  read -r -p "Başlık: " BASLIK
  while [ -z "$BASLIK" ]; do
    echo -e "${RED}Başlık boş bırakılamaz!${NC}"
    read -r -p "Başlık: " BASLIK
  done

  echo -e "\n${BOLD}5. Detaylı Açıklama / Tekrarlama Adımları:${NC}"
  echo -e "${DIM}(Ne yaptınız, ne bekliyordunuz, ne oldu?)${NC}"
  read -r -p "Açıklama: " ACIKLAMA

  echo
  echo -e "${YELLOW}⏳ Bildirim kaydediliyor...${NC}"
  $PY scripts/musteri_talepleri.py --yeni --tur "$TUR" --oncelik "$ONCELIK" --sayfa "$SAYFA" --baslik "$BASLIK" --aciklama "$ACIKLAMA"
  
  echo
  echo -e "${GREEN}✓ Talebiniz başarıyla kayıt altına alındı!${NC}"
  echo -e "${CYAN}ℹ️  Studio Yetkilisinin plan çıkarması için 'Studio Yetkilisini Çağır' seçeneğini kullanabilirsiniz.${NC}"
  echo
  read -r -p "Devam etmek için Enter'a basın..." _
}

case "${1:-}" in
  --yardim|-h)
    echo -e "${BOLD}Kullanım:${NC}"
    echo "  ./musteri.sh                         İnteraktif menüyü açar"
    echo "  ./musteri.sh --liste                 Tüm bildirimleri ve durumlarını listeler"
    echo "  ./musteri.sh --hata \"Başlık\" \"Detay\" [Sayfa]   Hızlı hata kaydı oluşturur"
    echo "  ./musteri.sh --istek \"Başlık\" \"Detay\" [Sayfa]  Hızlı özellik talebi oluşturur"
    echo "  ./musteri.sh --planla [TALEP-ID]      Studio yetkilisini tetikleyip çözüm planı çıkartır"
    echo "  ./musteri.sh --hepsini-planla        Bekleyen tüm talepleri planlar"
    echo "  ./musteri.sh --cozuldu [TALEP-ID]    Talebi çözüldü olarak onaylar"
    echo "  ./musteri.sh --triage                Karar verici triage ve fazlama denetimini çalıştırır"
    echo "  ./musteri.sh --fazlar                Yol haritası fazlarını ve durumlarını listeler"
    echo "  ./musteri.sh --ata [ID] [FAZ]        Talebi belirtilen faza aktarır (örn: --ata TALEP-012 FAZ-2)"
    exit 0
    ;;
  --triage|--karar)
    $PY scripts/karar_verici_triage.py --liste
    exit 0
    ;;
  --fazlar)
    $PY scripts/karar_verici_triage.py --liste
    exit 0
    ;;
  --ata)
    [ -z "${2:-}" ] && { echo -e "${RED}Talep ID gerekli!${NC}"; exit 1; }
    $PY scripts/karar_verici_triage.py --ata "$2" --faz "${3:-FAZ-2}"
    exit 0
    ;;
  --liste)
    $PY scripts/musteri_talepleri.py --liste
    exit 0
    ;;
  --hata)
    [ -z "${2:-}" ] && { echo -e "${RED}Hata başlığı gerekli!${NC}"; exit 1; }
    $PY scripts/musteri_talepleri.py --yeni --tur "HATA" --baslik "$2" --aciklama "${3:-$2}" --sayfa "${4:-/}"
    exit 0
    ;;
  --istek)
    [ -z "${2:-}" ] && { echo -e "${RED}İstek başlığı gerekli!${NC}"; exit 1; }
    $PY scripts/musteri_talepleri.py --yeni --tur "ISTEK" --baslik "$2" --aciklama "${3:-$2}" --sayfa "${4:-/}"
    exit 0
    ;;
  --planla)
    [ -z "${2:-}" ] && { echo -e "${RED}Talep ID'si gerekli (örn: TALEP-001)!${NC}"; exit 1; }
    $PY scripts/studio_yetkilisi.py --planla "$2"
    exit 0
    ;;
  --hepsini-planla)
    $PY scripts/studio_yetkilisi.py --hepsini-planla
    exit 0
    ;;
  --cozuldu)
    [ -z "${2:-}" ] && { echo -e "${RED}Talep ID'si gerekli!${NC}"; exit 1; }
    $PY scripts/studio_yetkilisi.py --cozum-onayla "$2"
    exit 0
    ;;
esac

# Eğer parametre doğrudan metin ise hızlı talep olarak al
if [ -n "${1:-}" ]; then
  $PY scripts/musteri_talepleri.py --yeni --tur "HATA" --baslik "$1" --aciklama "${2:-$1}" --sayfa "${3:-/}"
  exit 0
fi

# Ana İnteraktif Menü Döngüsü
while true; do
  header
  echo -e "${BOLD}Müşteri Denetim Menüsü:${NC}"
  echo -e "  ${CYAN}1)${NC} ✍️  Yeni Hata / İstek Bildir"
  echo -e "  ${CYAN}2)${NC} 📋 Talepleri ve Durumları Listele"
  echo -e "  ${CYAN}3)${NC} 🔍 Belirli Bir Talebi İncele"
  echo -e "  ${CYAN}4)${NC} 🧠 Studio Yetkilisini Çağır (Bekleyenleri Çözüm İçin Planla)"
  echo -e "  ${CYAN}5)${NC} 🌐 Canlı Test Ortamını Başlat (Nuxt & Fastify)"
  echo -e "  ${CYAN}6)${NC} 📑 Talep Havuzu Dosyasını Aç (musteri_talepleri.md)"
  echo -e "  ${CYAN}7)${NC} ⚖️  Karar Verici Masası (Triage, Fazlama & Onay)"
  echo -e "  ${CYAN}0)${NC} Çıkış"
  echo
  read -r -p "Seçiminiz [0-7]: " SECIM

  case "$SECIM" in
    1)
      yeni_bildirim_formu
      ;;
    2)
      header
      $PY scripts/musteri_talepleri.py --liste
      echo
      read -r -p "Devam etmek için Enter'a basın..." _
      ;;
    3)
      echo
      read -r -p "İncelemek istediğiniz Talep ID (örn: TALEP-001): " TID
      if [ -n "$TID" ]; then
        echo
        $PY scripts/musteri_talepleri.py --goster "$TID" || true
        PLAN_FILE="workspace/docs/cozum_planlari/${TID}.md"
        if [ -f "$PLAN_FILE" ]; then
          echo -e "\n${GREEN}📄 Çözüm Planı Mevcut:${NC} $PLAN_FILE"
        fi
      fi
      echo
      read -r -p "Devam etmek için Enter'a basın..." _
      ;;
    4)
      header
      echo -e "${YELLOW}🧠 Studio Yetkilisi bekleyen talepleri inceliyor ve çözüm planları üretiyor...${NC}\n"
      $PY scripts/studio_yetkilisi.py --hepsini-planla
      echo
      read -r -p "Devam etmek için Enter'a basın..." _
      ;;
    5)
      echo -e "\n${BLUE}🌐 Canlı geliştirme ortamı açılıyor (Ctrl+C ile durdurulabilir)...${NC}"
      sleep 1
      ./canli.sh
      ;;
    6)
      echo -e "\n${GREEN}workspace/docs/musteri_talepleri.md açılıyor:${NC}"
      cat workspace/docs/musteri_talepleri.md 2>/dev/null || echo "Dosya henüz boş."
      echo
      read -r -p "Devam etmek için Enter'a basın..." _
      ;;
    7)
      header
      $PY scripts/karar_verici_triage.py --liste
      echo
      echo -e "${YELLOW}Talebi bir faza atamak ister misiniz? (Örn: TALEP-012 FAZ-2)${NC}"
      read -r -p "Talep ID ve Hedef Faz (Boş geçmek için Enter): " ATAMA_GIRDI
      if [ -n "$ATAMA_GIRDI" ]; then
        T_ID=$(echo "$ATAMA_GIRDI" | awk '{print $1}')
        F_ID=$(echo "$ATAMA_GIRDI" | awk '{print $2}')
        [ -z "$F_ID" ] && F_ID="FAZ-2"
        $PY scripts/karar_verici_triage.py --ata "$T_ID" --faz "$F_ID"
      fi
      echo
      read -r -p "Devam etmek için Enter'a basın..." _
      ;;
    0|q|Q)
      echo -e "\n${GREEN}İyi çalışmalar!${NC}\n"
      exit 0
      ;;
    *)
      echo -e "\n${RED}Geçersiz seçim!${NC}"
      sleep 1
      ;;
  esac
done
