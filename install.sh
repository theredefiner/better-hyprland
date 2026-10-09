#!/usr/bin/env bash
# =====================================================================
#  Better Hyprland v0.1 Beta - Installer
#  Run it from inside the Better_Hyprland_v0.1_Beta folder:
#       chmod +x install.sh && ./install.sh
#  Do NOT run it with sudo (it asks for your password when needed).
# =====================================================================
set -Eeuo pipefail
trap 'printf "\n\033[1;31m[error]\033[0m Something failed near line %s. Installation stopped.\n" "$LINENO" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$HOME/.config"
BACKUP_DIR="$HOME/.better-hyprland-backup/$(date +%Y%m%d-%H%M%S)"

# ---------- pretty output ----------
if [[ -t 1 ]]; then
  BOLD=$'\033[1m'; RED=$'\033[1;31m'; GRN=$'\033[1;32m'
  YEL=$'\033[1;33m'; MAG=$'\033[1;35m'; RST=$'\033[0m'
else
  BOLD=""; RED=""; GRN=""; YEL=""; MAG=""; RST=""
fi
step() { printf '\n%s==>%s %s%s%s\n' "$MAG" "$RST" "$BOLD" "$*" "$RST"; }
info() { printf '    %s\n' "$*"; }
ok()   { printf '    %s[ok]%s %s\n' "$GRN" "$RST" "$*"; }
warn() { printf '    %s[warn]%s %s\n' "$YEL" "$RST" "$*"; }
die()  { printf '%s[error]%s %s\n' "$RED" "$RST" "$*" >&2; exit 1; }

ask_yn() {
  local ans
  while true; do
    read -r -p "$1 [y/n] " ans
    case "$ans" in
      [Yy]) return 0 ;;
      [Nn]) return 1 ;;
      *) echo "    Please type y or n." ;;
    esac
  done
}

need_dir() { [[ -d "$SCRIPT_DIR/$1" ]] || die "Folder '$1' is missing next to install.sh. Re-download the pack."; }
need_file() { [[ -f "$SCRIPT_DIR/$1" ]] || die "File '$1' is missing next to install.sh. Re-download the pack."; }

# ---------- banner & sanity checks ----------
clear 2>/dev/null || true
printf '%s' "$MAG"
cat <<'BANNER'
  ____       _   _            _   _                  _                 _
 | __ )  ___| |_| |_ ___ _ __| | | |_   _ _ __  _ __| | __ _ _ __   __| |
 |  _ \ / _ \ __| __/ _ \ '__| |_| | | | | '_ \| '__| |/ _` | '_ \ / _` |
 | |_) |  __/ |_| ||  __/ |  |  _  | |_| | |_) | |  | | (_| | | | | (_| |
 |____/ \___|\__|\__\___|_|  |_| |_|\__, | .__/|_|  |_|\__,_|_| |_|\__,_|
                                    |___/|_|          v0.1 Beta
BANNER
printf '%s\n' "$RST"

[[ $EUID -ne 0 ]] || die "Do not run this script as root or with sudo. Run it as your normal user."
command -v pacman >/dev/null 2>&1 || die "This installer is for Arch Linux (pacman was not found)."

for d in waybar rofi swaync hypr Fonts/Google_Sans_Flex wallpaper_fix; do need_dir "$d"; done
for f in waybar/style.css waybar/config.jsonc rofi/win11.rasi rofi/config.rasi \
         swaync/config.json swaync/style.css hypr/hyprland.lua hypr/hyprlock.conf \
         wallpaper_fix/wall0.png; do need_file "$f"; done

info "Your password is needed for installing packages."
sudo -v

# =====================================================================
# 1. Check dependencies
# =====================================================================
step "Step 1/6: Checking dependencies"

DEPS=(
  waybar rofi swaync grim slurp swappy hyprsunset networkmanager
  waypaper hyprpaper gtk3 gtk4
  ttf-nerd-fonts-symbols-mono ttf-jetbrains-mono-nerd
)
# Also needed by this rice (lock screen, screenshot copy, brightness slider,
# rofi app icons, Bluetooth toggle)
EXTRA_DEPS=(hyprlock wl-clipboard brightnessctl papirus-icon-theme bluez bluez-utils)

# 'pacman -T' prints only the packages that are NOT satisfied
mapfile -t MISSING < <(pacman -T "${DEPS[@]}" "${EXTRA_DEPS[@]}" || true)

if [[ ${#MISSING[@]} -eq 0 ]]; then
  ok "All dependencies are already installed. Skipping."
else
  info "Missing: ${MISSING[*]}"
  REPO_PKGS=(); AUR_PKGS=()
  for p in "${MISSING[@]}"; do
    if pacman -Si "$p" >/dev/null 2>&1; then REPO_PKGS+=("$p"); else AUR_PKGS+=("$p"); fi
  done

  if [[ ${#REPO_PKGS[@]} -gt 0 ]]; then
    info "Installing from the official repos: ${REPO_PKGS[*]}"
    sudo pacman -S --needed "${REPO_PKGS[@]}"
  fi

  if [[ ${#AUR_PKGS[@]} -gt 0 ]]; then
    info "Not in the official repos (AUR): ${AUR_PKGS[*]}"
    HELPER=""
    command -v yay  >/dev/null 2>&1 && HELPER="yay"
    [[ -z "$HELPER" ]] && command -v paru >/dev/null 2>&1 && HELPER="paru"
    if [[ -n "$HELPER" ]]; then
      info "Using $HELPER"
      "$HELPER" -S --needed "${AUR_PKGS[@]}" || warn "AUR install failed. Install manually: ${AUR_PKGS[*]}"
    else
      info "No AUR helper (yay/paru) found. Building the packages with git + makepkg."
      sudo pacman -S --needed git base-devel
      for p in "${AUR_PKGS[@]}"; do
        TMP="$(mktemp -d)"
        if git clone "https://aur.archlinux.org/${p}.git" "$TMP/$p" && (cd "$TMP/$p" && makepkg -si); then
          ok "$p built and installed."
        else
          warn "Could not build $p. Install it manually later (needed for wallpapers if it is waypaper)."
        fi
        rm -rf "$TMP"
      done
    fi
  fi
  ok "Dependency step finished."
fi

# =====================================================================
# 2. Google Sans Flex font
# =====================================================================
step "Step 2/6: Installing the Google Sans Flex font"

FONT_DST="$HOME/.local/share/fonts/GoogleSansFlex"
mkdir -p "$FONT_DST"
cp -f "$SCRIPT_DIR"/Fonts/Google_Sans_Flex/*.ttf "$FONT_DST/"
info "Refreshing the font cache..."
fc-cache -f "$HOME/.local/share/fonts"
if fc-list | grep -qi "google sans flex"; then
  ok "Google Sans Flex is installed."
else
  warn "Font copied, but fontconfig can't see it yet. Log out and back in if the text looks wrong."
fi

# =====================================================================
# Backup of your current configs (safety copy)
# =====================================================================
step "Saving a backup of your current configs"
mkdir -p "$BACKUP_DIR"
for d in waybar rofi swaync hypr; do
  [[ -e "$CONFIG_DIR/$d" ]] && cp -a "$CONFIG_DIR/$d" "$BACKUP_DIR/" || true
done
ok "Backup saved in: $BACKUP_DIR"

# =====================================================================
# 3. Waybar
# =====================================================================
step "Step 3/6: Configuring Waybar"
mkdir -p "$CONFIG_DIR/waybar"
cp -f "$SCRIPT_DIR/waybar/style.css" "$SCRIPT_DIR/waybar/config.jsonc" "$CONFIG_DIR/waybar/"
ok "Waybar config installed."

# =====================================================================
# 4. Rofi (start menu)
# =====================================================================
step "Step 4/6: Configuring the Rofi start menu"
mkdir -p "$CONFIG_DIR/rofi"
cp -f "$SCRIPT_DIR/rofi/win11.rasi" "$SCRIPT_DIR/rofi/config.rasi" "$CONFIG_DIR/rofi/"
# If the pack was made on another user's account, point absolute paths at this user's home
sed -i -E "s|/home/[A-Za-z0-9._-]+/|$HOME/|g" "$CONFIG_DIR/rofi/config.rasi"
ok "Rofi theme installed."

# =====================================================================
# 5. SwayNC
# =====================================================================
step "Step 5/6: Configuring SwayNC (quick settings + notifications)"
mkdir -p "$CONFIG_DIR/swaync"
cp -f "$SCRIPT_DIR/swaync/config.json" "$SCRIPT_DIR/swaync/style.css" "$CONFIG_DIR/swaync/"
ok "SwayNC config installed."

# =====================================================================
# 6. Hyprland keybinds, animations and lock screen
# =====================================================================
step "Step 6/6: Configuring Hyprland keybinds and animations"
echo
echo "${YEL}  WARNING:${RST} If you have any important thing in your Hyprland"
echo "  configuration file, please recover it first."
echo "  This script will replace it with the new one. (A backup copy is in:"
echo "  $BACKUP_DIR)"
echo "  And please do not exit while it is installing."
echo
if ask_yn "  Are you sure to install?"; then
  mkdir -p "$CONFIG_DIR/hypr"
  rm -rf "$CONFIG_DIR/hypr/hyprland.lua"
  cp -f "$SCRIPT_DIR/hypr/hyprland.lua" "$SCRIPT_DIR/hypr/hyprlock.conf" "$CONFIG_DIR/hypr/"
  [[ -f "$SCRIPT_DIR/hypr/hyprland.lua.bak" ]] && cp -f "$SCRIPT_DIR/hypr/hyprland.lua.bak" "$CONFIG_DIR/hypr/"
  sed -i -E "s|/home/[A-Za-z0-9._-]+/|$HOME/|g" "$CONFIG_DIR/hypr/hyprland.lua"
  mkdir -p "$HOME/Pictures"
  ok "hyprland.lua and hyprlock.conf installed."

  info "Applying the wallpaper fix (Hyprland's default wallpapers)..."
  WALL_DIR="/usr/share/hypr"
  if [[ -d "$WALL_DIR" ]]; then
    sudo rm -f "$WALL_DIR/wall0.png" "$WALL_DIR/wall1.png" "$WALL_DIR/wall2.png"
    sudo cp -f "$SCRIPT_DIR/wallpaper_fix/wall0.png" "$WALL_DIR/"
    ok "Wallpaper fix applied."
  else
    warn "$WALL_DIR was not found, skipping the wallpaper fix."
  fi

  if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]] && command -v hyprctl >/dev/null 2>&1; then
    info "Reloading Hyprland..."
    hyprctl reload || warn "hyprctl reload reported a problem. Check the error bar at the top of the screen."
  else
    info "Hyprland is not running right now. The config will load on your next login."
  fi
else
  warn "Skipped the Hyprland step. Keybinds, animations and blur rules were NOT installed."
fi

# =====================================================================
# Post-installation
# =====================================================================
step "Required post-installation steps"
if pacman -Q bluez >/dev/null 2>&1; then
  sudo systemctl enable --now bluetooth.service >/dev/null 2>&1 \
    && ok "Bluetooth service enabled." || warn "Could not enable the bluetooth service."
fi
systemctl is-active --quiet NetworkManager || warn "NetworkManager is not running (the Wi-Fi toggle needs it)."

echo
echo "${GRN}  Better Hyprland v0.1 Beta is successfully installed.${RST}"
echo
echo "  Post-installation notes:"
echo "   - Check the keybinds in README.md."
echo "   - You must set your wallpaper from the Waypaper app."
echo "   - Backup of your old configs: $BACKUP_DIR"
echo
read -r -p "  Proceed to restart now? [Press Enter after you have read this] "

# =====================================================================
# Reboot
# =====================================================================
step "Rebooting your PC"
echo "  Press Ctrl+C within 5 seconds to cancel."
sleep 5
systemctl reboot || reboot
