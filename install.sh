#!/usr/bin/env bash
# =====================================================================
#  Better Hyprland v1.0 Stable - Installer
#  Run it from inside the Better_Hyprland_v1.0_Stable folder:
#       chmod +x install.sh && ./install.sh
#  Do NOT run it with sudo (it asks for your password when needed).
#
#  Copyright (C) 2026 theredefiner
#
#  This program is free software: you can redistribute it and/or modify it
#  under the terms of the GNU General Public License as published by the Free
#  Software Foundation, either version 3 of the License, or (at your option)
#  any later version. It is distributed WITHOUT ANY WARRANTY.
#
#  Third-party fonts and packages keep their own licenses.
# =====================================================================
set -Eeuo pipefail
trap 'printf "\n\033[1;31m[error]\033[0m Something failed near line %s. Installation stopped.\n" "$LINENO" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$HOME/.config"
FONT_DST="$HOME/.local/share/fonts"
BACKUP_DIR="$HOME/.better-hyprland-backup/$(date +%Y%m%d-%H%M%S)"
FAILED=()          # AUR packages that could not be installed
SKIP_HYPR=0

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

# Default answer is NO. Only y / yes continues.
ask_yn() {
  local ans
  read -r -p "$1 [y/N]: " ans
  [[ "$ans" =~ ^[Yy]([Ee][Ss])?$ ]]
}

need_dir()  { [[ -d "$SCRIPT_DIR/$1" ]] || die "Folder '$1' is missing next to install.sh. Re-download the pack."; }
need_file() { [[ -f "$SCRIPT_DIR/$1" ]] || die "File '$1' is missing next to install.sh. Re-download the pack."; }

# Copy something from ~/.config into the backup folder (if it exists)
backup() {
  [[ -e "$1" ]] || return 0
  mkdir -p "$BACKUP_DIR"
  cp -a "$1" "$BACKUP_DIR/"
}

# If the pack was made on another user's account, point /home/<name>/ paths at this user's home
fix_paths() {
  local f
  for f in "$@"; do
    [[ -f "$f" ]] || continue
    if grep -qE '/home/[A-Za-z0-9._-]+/' "$f"; then
      sed -i -E "s|/home/[A-Za-z0-9._-]+/|$HOME/|g" "$f"
      info "Updated home paths in ${f#"$HOME"/}"
    fi
  done
}

# Install an AUR package, but don't kill the whole installer if one build fails
aur_install() {
  local pkg="$1"
  if yay -S --needed --noconfirm "$pkg"; then
    ok "$pkg installed."
  else
    warn "Could not install $pkg. Install it manually later:  yay -S $pkg"
    FAILED+=("$pkg")
  fi
}

# ---------- banner & sanity checks ----------
clear 2>/dev/null || true
printf '%s' "$MAG"
cat <<'BANNER'
  ____       _   _            _   _                  _                 _
 | __ )  ___| |_| |_ ___ _ __| | | |_   _ _ __  _ __| | __ _ _ __   __| |
 |  _ \ / _ \ __| __/ _ \ '__| |_| | | | | '_ \| '__| |/ _` | '_ \ / _` |
 | |_) |  __/ |_| ||  __/ |  |  _  | |_| | |_) | |  | | (_| | | | | (_| |
 |____/ \___|\__|\__\___|_|  |_| |_|\__, | .__/|_|  |_|\__,_|_| |_|\__,_|
                                    |___/|_|          v1.0 Stable
BANNER
printf '%s\n' "$RST"

[[ $EUID -ne 0 ]] || die "Do not run this script as root or with sudo. Run it as your normal user."
command -v pacman >/dev/null 2>&1 || die "This installer is for Arch Linux (pacman was not found)."

for d in Fonts hypr kitty better-hyprland better-hyprland/nc better-hyprland/sm; do need_dir "$d"; done
for f in hypr/hyprland.lua hypr/hyprlock.conf \
         kitty/kitty.conf kitty/current-theme.conf \
         starship.toml \
         better-hyprland/bar_main.py better-hyprland/charging_overlay.py \
         better-hyprland/emoji-picker.py better-hyprland/sound.mp3; do need_file "$f"; done

info "Your password is needed for installing packages."
sudo -v

# =====================================================================
# Step 1: Prerequisites
# =====================================================================
step "Step 1/8: Installing prerequisites"
sudo pacman -S --needed --noconfirm \
  python python-pyqt6 qt6-wayland layer-shell-qt python-fonttools python-gobject \
  git base-devel papirus-icon-theme kitty hyprlock \
  grim slurp wl-clipboard brightnessctl bluez bluez-utils networkmanager \
  swappy hyprsunset gtk3 gtk4 playerctl power-profiles-daemon \
  ttf-jetbrains-mono-nerd ttf-nerd-fonts-symbols-mono ttf-jetbrains-mono
ok "Packages installed."

info "Copying fonts (Font Awesome 7, Google Sans Flex 9pt, Material Symbols)..."
mkdir -p "$FONT_DST"
cp -rf "$SCRIPT_DIR"/Fonts/* "$FONT_DST/"
fc-cache -f "$FONT_DST"
ok "Fonts copied to $FONT_DST"

# =====================================================================
# Step 2: Hyprland config and desktop experience
# =====================================================================
step "Step 2/8: Hyprland config and desktop experience"
echo
echo "${YEL}  WARNING:${RST} This replaces your whole ~/.config/hypr folder (including hyprland.lua)"
echo "  and ~/.config/better-hyprland. A backup copy is saved in:"
echo "  $BACKUP_DIR"
echo "  If you have anything important in there, recover it first."
echo
if ask_yn "  This setup will wipe your hyprland.lua file. Proceed with it?"; then
  backup "$CONFIG_DIR/hypr"
  backup "$CONFIG_DIR/better-hyprland"
  mkdir -p "$CONFIG_DIR"

  rm -rf "$CONFIG_DIR/hypr" "$CONFIG_DIR/better-hyprland"
  cp -r "$SCRIPT_DIR/hypr" "$CONFIG_DIR/"
  cp -r "$SCRIPT_DIR/better-hyprland" "$CONFIG_DIR/"

  fix_paths "$CONFIG_DIR"/hypr/hyprland.lua "$CONFIG_DIR"/hypr/hyprlock.conf
  mapfile -d '' -t BH_FILES < <(find "$CONFIG_DIR/better-hyprland" -type f \
    \( -name '*.py' -o -name '*.json' -o -name '*.css' -o -name '*.conf' \) -print0)
  [[ ${#BH_FILES[@]} -eq 0 ]] || fix_paths "${BH_FILES[@]}"

  ok "Hyprland config and Better Hyprland desktop files installed."
else
  SKIP_HYPR=1
  warn "Skipped. Your Hyprland config was NOT changed, so the Better Hyprland desktop will not load."
fi

# =====================================================================
# Step 3: Kitty, Starship and Fish
# =====================================================================
step "Step 3/8: Kitty terminal, Starship prompt and Fish shell"
sudo pacman -S --needed --noconfirm starship fish
backup "$CONFIG_DIR/starship.toml"
backup "$CONFIG_DIR/kitty"
mkdir -p "$CONFIG_DIR"
cp -f  "$SCRIPT_DIR/starship.toml" "$CONFIG_DIR/"
cp -rf "$SCRIPT_DIR/kitty" "$CONFIG_DIR/"
fix_paths "$CONFIG_DIR"/kitty/*.conf
ok "Starship and Kitty configured."

# =====================================================================
# Step 4: AUR helper (yay)
# =====================================================================
step "Step 4/8: AUR helper (yay)"
if command -v yay >/dev/null 2>&1; then
  ok "yay is already installed. Skipping."
else
  TMP="$(mktemp -d)"
  git clone https://aur.archlinux.org/yay.git "$TMP/yay"
  (cd "$TMP/yay" && makepkg -si --noconfirm)
  rm -rf "$TMP"
  ok "yay installed."
fi

# =====================================================================
# Step 5: Wallpaper selector
# =====================================================================
step "Step 5/8: Wallpaper selector (hyprpaper + waypaper)"
sudo pacman -S --needed --noconfirm hyprpaper
aur_install waypaper

# =====================================================================
# Step 6: Emoji pack
# =====================================================================
step "Step 6/8: Apple emoji pack"
aur_install ttf-apple-emoji
EMOJI_CONF="/usr/share/fontconfig/conf.avail/75-apple-color-emoji.conf"
if [[ -e "$EMOJI_CONF" ]]; then
  sudo ln -sf "$EMOJI_CONF" /etc/fonts/conf.d/
  ok "Apple emoji enabled in fontconfig."
else
  warn "$EMOJI_CONF not found, so Apple emoji was not enabled (is ttf-apple-emoji installed?)."
fi
fc-cache -f
FC_OUT="$(fc-list)"
grep -qi "google sans" <<<"$FC_OUT" || warn "Google Sans Flex isn't visible to fontconfig yet. Log out and back in if the text looks wrong."

# =====================================================================
# Step 7: Browser
# =====================================================================
step "Step 7/8: Brave browser"
aur_install brave-bin

# =====================================================================
# Step 8: Post installation
# =====================================================================
step "Step 8/8: Post installation"
if [[ ${#FAILED[@]} -gt 0 ]]; then
  warn "These packages failed to install: ${FAILED[*]}"
  warn "Install them manually after the restart:  yay -S ${FAILED[*]}"
fi
sudo systemctl enable --now bluetooth.service >/dev/null 2>&1 \
  && ok "Bluetooth service enabled." || warn "Could not enable the bluetooth service."
sudo systemctl enable --now power-profiles-daemon.service >/dev/null 2>&1 \
  && ok "Power profiles service enabled." || warn "Could not enable power-profiles-daemon (the Performance toggle needs it)."
systemctl is-active --quiet NetworkManager || warn "NetworkManager is not running (the Wi-Fi toggle needs it). Enable it with: sudo systemctl enable --now NetworkManager"
[[ $SKIP_HYPR -eq 0 ]] || warn "You skipped the Hyprland config step, so it was not installed."
[[ ! -d "$BACKUP_DIR" ]] || info "Backup of your old configs: $BACKUP_DIR"
echo
read -r -p "  This is successfully installed. Your PC needs a restart to work perfectly. Save your works and press enter to restart: "

echo
echo "${GRN}  Thanks for using Better Hyprland${RST}"
sleep 2
systemctl reboot || reboot
