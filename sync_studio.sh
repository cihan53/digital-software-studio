#!/usr/bin/env bash
# ==============================================================================
#  sync_studio.sh — Digital Software Studio → Proje Senkronizasyon Aracı
#
#  Güncelleme TEK YÖNLÜDÜR: her zaman studio → proje.
#  Gerçek iş scripts/studio_updater.py tarafından yapılır (studio.version'daki
#  tracked_files/protected_files listesine göre, STUDIO:CUSTOM blokları korunarak).
#  Bu script yalnızca geriye uyumlu bir kısayoldur.
#
#  Kullanım:
#    ./sync_studio.sh --durum             # Fark + versiyon raporu (yazmaz)
#    ./sync_studio.sh --studio-guncelle   # Studio → bu proje (damga dahil)
#    ./sync_studio.sh --studio-guncelle --force   # protected_files'ı da ez
#    ./sync_studio.sh --studio-guncelle --commit  # + otomatik git commit/push
#
#  Studio'ya katkı: digital-software-studio reposunda normal git akışıyla
#  (issue → branch → PR) yapılır; projeden dosya kopyalanmaz.
# ==============================================================================

set -eo pipefail
cd "$(dirname "$0")" || exit 1

PROJE_ADI="$(basename "$(pwd)")"
UPDATER="scripts/studio_updater.py"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'
RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'

header() {
    echo -e "\n${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}  🔄  ${BOLD}Studio Sync${NC} — ${PROJE_ADI} (tek yön: studio → proje)  ${CYAN}║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}\n"
}

updater_var_mi() {
    if [ ! -f "$UPDATER" ]; then
        echo -e "${RED}✗ $UPDATER bulunamadı.${NC}"
        echo -e "  ${YELLOW}Önce framework dosyalarını güncelleyin ya da scripti"
        echo -e "  studio reposundan kopyalayın.${NC}"
        exit 1
    fi
}

cmd_durum() {
    header
    updater_var_mi
    python3 "$UPDATER" --kontrol
}

cmd_studio_guncelle() {
    header
    updater_var_mi
    echo -e "${YELLOW}📥 digital-software-studio → ${PROJE_ADI}${NC}"
    python3 "$UPDATER" --uygula "$@"
}

kaldirildi() {
    header
    echo -e "${YELLOW}⚠️  '$1' kaldırıldı — senkronizasyon artık tek yönlü: studio → proje.${NC}"
    echo -e "  Güncellemek için : ${CYAN}./sync_studio.sh --studio-guncelle${NC}"
    echo -e "  Studio'ya katkı  : digital-software-studio reposunda issue → branch → PR\n"
}

case "${1:-}" in
    --durum|--status|--kontrol)
        shift; cmd_durum ;;
    --studio-guncelle|--uygula|--guncelle)
        shift; cmd_studio_guncelle "$@" ;;
    --studio-al)
        kaldirildi "--studio-al" ;;
    --tam-senkron)
        kaldirildi "--tam-senkron" ;;
    *)
        echo "Kullanım:"
        echo "  ./sync_studio.sh --durum                     Fark + versiyon raporu"
        echo "  ./sync_studio.sh --studio-guncelle           Studio → Bu proje"
        echo "  ./sync_studio.sh --studio-guncelle --force   protected_files'ı da üzerine yaz"
        echo "  ./sync_studio.sh --studio-guncelle --commit  + otomatik git commit & push"
        echo ""
        echo "Not: Senkronizasyon tek yönlüdür (studio → proje). Studio'ya katkı"
        echo "     digital-software-studio reposunda issue → branch → PR ile yapılır."
        ;;
esac
