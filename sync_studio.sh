#!/usr/bin/env bash
# ==============================================================================
#  sync_studio.sh — Digital Software Studio ↔ Proje Senkronizasyon Aracı
#
#  Kullanım:
#    ./sync_studio.sh --durum                  # Fark raporu (push etmez)
#    ./sync_studio.sh --studio-guncelle        # digital-studio → bu proje
#    ./sync_studio.sh --studio-al              # bu proje → digital-studio (proje-agnostik)
#    ./sync_studio.sh --tam-senkron            # iki yönlü eşitle + commit + push
# ==============================================================================

set -eo pipefail
cd "$(dirname "$0")" || exit 1

STUDIO_REPO="${STUDIO_REPO:-/Users/cihan/PROJECT/digital-software-studio}"
PROJE_REPO="$(pwd)"
PROJE_ADI="$(basename "$PROJE_REPO")"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'
RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'

# Framework dosyaları — bu dosyalar iki yönlü senkronize edilir
# Değer: "studio_dosyası:proje_dosyası" (aynıysa tek yol)
FRAMEWORK_DOSYALAR=(
    "studio_board.py"
    "studio_ctl.py"
    "scripts/musteri_talepleri.py"
    "scripts/karar_verici_triage.py"
    "scripts/github_issue_bridge.py"
    "scripts/recovery_sentinel.py"
    "scripts/kalite_kapilari.py"
)

# Yalnızca studio→proje yönünde güncellenen (proje özelleştirmesi olmayan) dosyalar
STUDIO_ONLY_DOSYALAR=(
    "scripts/studio_yetkilisi.py"
    "musteri.sh"
)

# Yalnızca proje→studio yönünde (proje özel içerik, agnostik hale getirilerek)
PROJE_ONLY_AGNOSTIK=(
    # Bunlar agnostik dönüşüm gerektiriyor — manuel işlem
)

# Proje'ye özel, asla sync edilmeyen dosyalar
PROJE_OZELI=(
    "studio_engine.py"   # UAT rotaları proje-özel
    "basla.sh"           # Proje-özel başlatma mantığı
)

header() {
    echo -e "\n${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}  🔄  ${BOLD}Studio Sync${NC} — ${PROJE_ADI}                        ${CYAN}║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}\n"
}

studio_var_mi() {
    if [ ! -d "$STUDIO_REPO" ]; then
        echo -e "${RED}✗ Digital Software Studio bulunamadı: $STUDIO_REPO${NC}"
        echo -e "  ${YELLOW}STUDIO_REPO ortam değişkeni ile yolu belirtin.${NC}"
        exit 1
    fi
}

dosya_durum() {
    local proje_dosya="$PROJE_REPO/$1"
    local studio_dosya="$STUDIO_REPO/$1"

    if [ ! -f "$proje_dosya" ] && [ ! -f "$studio_dosya" ]; then
        echo "❓ HER İKİSİNDE YOK"
    elif [ ! -f "$proje_dosya" ]; then
        echo "🟡 SADECE STUDIO'DA VAR"
    elif [ ! -f "$studio_dosya" ]; then
        echo "🔵 SADECE PROJEDE VAR"
    elif diff -q "$proje_dosya" "$studio_dosya" > /dev/null 2>&1; then
        echo "✅ AYNI"
    else
        local proje_b studio_b
        proje_b=$(wc -c < "$proje_dosya")
        studio_b=$(wc -c < "$studio_dosya")
        local delta=$((proje_b - studio_b))
        if [ "$delta" -gt 0 ]; then
            echo "🔵 PROJE +${delta}B önde"
        else
            echo "🟡 STUDIO +$((-delta))B önde"
        fi
    fi
}

cmd_durum() {
    header
    studio_var_mi
    echo -e "${BOLD}Framework Dosyaları (iki yönlü sync):${NC}"
    for f in "${FRAMEWORK_DOSYALAR[@]}"; do
        durum=$(dosya_durum "$f")
        printf "  %-45s %s\n" "$f" "$durum"
    done

    echo -e "\n${BOLD}Studio→Proje Dosyaları:${NC}"
    for f in "${STUDIO_ONLY_DOSYALAR[@]}"; do
        durum=$(dosya_durum "$f")
        printf "  %-45s %s\n" "$f" "$durum"
    done

    echo -e "\n${BOLD}Proje-Özel (sync edilmez):${NC}"
    for f in "${PROJE_OZELI[@]}"; do
        printf "  %-45s 🔒 PROJE-ÖZEL\n" "$f"
    done
    echo ""
}

cmd_studio_guncelle() {
    header
    studio_var_mi
    echo -e "${YELLOW}📥 digital-software-studio → ${PROJE_ADI}${NC}\n"
    guncellenen=0

    # Framework dosyaları: studio'dan proje'ye kopyala (sadece farklıysa)
    for f in "${FRAMEWORK_DOSYALAR[@]}" "${STUDIO_ONLY_DOSYALAR[@]}"; do
        studio_f="$STUDIO_REPO/$f"
        proje_f="$PROJE_REPO/$f"
        [ ! -f "$studio_f" ] && continue

        if ! diff -q "$proje_f" "$studio_f" > /dev/null 2>&1; then
            mkdir -p "$(dirname "$proje_f")"
            cp "$studio_f" "$proje_f"
            echo -e "  ${GREEN}✓${NC} Güncellendi: $f"
            guncellenen=$((guncellenen + 1))
        fi
    done

    if [ "$guncellenen" -eq 0 ]; then
        echo -e "  ${GREEN}✅ Her şey güncel, güncelleme gerekmedi.${NC}"
    else
        echo -e "\n  ${GREEN}✓ $guncellenen dosya güncellendi.${NC}"
    fi
    echo ""
}

cmd_studio_al() {
    header
    studio_var_mi
    echo -e "${YELLOW}📤 ${PROJE_ADI} → digital-software-studio${NC}\n"
    echo -e "  ${YELLOW}⚠️  studio_yetkilisi.py proje-agnostik dönüşüm gerektirir.${NC}"
    echo -e "  Manuel işlem: python3 sync_agnostik.py çalıştırın.\n"

    # Framework dosyaları: proje'den studio'ya kopyala
    guncellenen=0
    for f in "${FRAMEWORK_DOSYALAR[@]}"; do
        proje_f="$PROJE_REPO/$f"
        studio_f="$STUDIO_REPO/$f"
        [ ! -f "$proje_f" ] && continue

        if ! diff -q "$proje_f" "$studio_f" > /dev/null 2>&1; then
            mkdir -p "$(dirname "$studio_f")"
            cp "$proje_f" "$studio_f"
            echo -e "  ${GREEN}✓${NC} Studio güncellendi: $f"
            guncellenen=$((guncellenen + 1))
        fi
    done

    if [ "$guncellenen" -eq 0 ]; then
        echo -e "  ${GREEN}✅ Framework dosyaları güncel.${NC}"
    fi
    echo ""
}

cmd_tam_senkron() {
    header
    studio_var_mi

    echo -e "${BOLD}Adım 1/4: Durum raporu${NC}"
    cmd_durum

    echo -e "${BOLD}Adım 2/4: Studio → Proje güncelleme${NC}"
    cmd_studio_guncelle

    echo -e "${BOLD}Adım 3/4: Proje → Studio güncelleme${NC}"
    cmd_studio_al

    # Proje commit
    echo -e "${BOLD}Adım 4/4: Commit & Push${NC}"
    cd "$PROJE_REPO"
    if ! git diff --quiet HEAD; then
        git add -A
        git commit -m "sync(studio): digital-software-studio framework güncellemesi senkronize edildi"
        git push
        echo -e "  ${GREEN}✓${NC} ${PROJE_ADI} push edildi."
    else
        echo -e "  ${GREEN}✅${NC} ${PROJE_ADI}: commit gereken değişiklik yok."
    fi

    # Studio commit
    cd "$STUDIO_REPO"
    if ! git diff --quiet HEAD; then
        git add -A
        git commit -m "sync(studio): ${PROJE_ADI} proje geliştirmeleri framework'e taşındı"
        git push
        echo -e "  ${GREEN}✓${NC} digital-software-studio push edildi."
    else
        echo -e "  ${GREEN}✅${NC} digital-software-studio: commit gereken değişiklik yok."
    fi
    echo ""
}

case "${1:-}" in
    --durum|--status)   cmd_durum ;;
    --studio-guncelle)  cmd_studio_guncelle ;;
    --studio-al)        cmd_studio_al ;;
    --tam-senkron)      cmd_tam_senkron ;;
    *)
        echo "Kullanım:"
        echo "  ./sync_studio.sh --durum           Fark raporu"
        echo "  ./sync_studio.sh --studio-guncelle  Studio → Bu proje"
        echo "  ./sync_studio.sh --studio-al        Bu proje → Studio"
        echo "  ./sync_studio.sh --tam-senkron      İki yönlü + commit + push"
        ;;
esac
