# 🌸 Better Hyprland v0.1 Beta

> A modern, slick, and polished desktop environment experience built for barebones Hyprland on Arch Linux. Featuring frosted glass blur, smooth slide animation curves, custom floating pill bars, and a macOS/Android-inspired Control Center.

---

## ✨ Features

- **Glassmorphic Transparency**: Frosted glass blur and subtle opacity powered by Hyprland decorations.
- **Slide Animation Curves**: Springy, cubic-bezier animations for fluid window and workspace transitions.
- **Floating Pill Waybar**: Minimalist dock panel displaying workspace indicators, CPU/RAM usage, battery status, and clock.
- **SwayNC Control Center**: Quick settings for Wi-Fi, Bluetooth, volume, brightness, Do Not Disturb, and centralized notifications.
- **Rofi App Launcher**: Clean, centered application grid designed for the Sakura theme aesthetic.
- **Instant Screen Snipping**: Built-in screenshot tool bound to `Super + Shift + S` that copies cropped captures directly to the clipboard.
- **Automated Backup & Path Fixes**: Safety installer script that backs up existing user configurations before setup.

---

## 🛠️ Installation

### 1. Prerequisites
Ensure `git` is installed on your Arch Linux system:
```bash
sudo pacman -S --needed git
``

### 2. Clone & Run Installer
Clone the repository and execute the installation script:
```bash
git clone [https://github.com/theredefiner/better-hyprland.git](https://github.com/theredefiner/better-hyprland.git)
cd better-hyprland
chmod +x install.sh
./install.sh
```

> ⚠️ **Important Note:** Do **NOT** run `./install.sh` with `sudo`. The script handles privileges automatically and will prompt for your `sudo` password only when installing packages.

---

## ⌨️ Keybindings

| Keybinding | Action |
| :--- | :--- |
| `Super` | Toggle Start Menu (Rofi Launcher) |
| `Super` + `Q` | Launch Terminal |
| `Super` + `C` | Close Active App / Window |
| `Super` + `P` | Exit Hyprland (Logout Session) |
| `Super` + `L` | Lock Screen (Hyprlock) |
| `Super` + `D` | Toggle Fullscreen Mode |
| `Super` + `Alt` + `Space` | Toggle Floating Mode |
| `Super` + `Shift` + `S` | Screen Snip (Copies capture directly to clipboard) |
| `Super` + `S` | Toggle Special Workspace |
| `Super` + `N` | Open Notification & Quick Settings Panel (SwayNC) |
| `Super` + `Shift` + `Left` / `Right` | Move Active Window to Left / Right Workspace |
| `Super` + `1-9` | Switch to Workspace Number |

---

## ⚠️ Known Limitations & Notes

1. **Wi-Fi Connections:**
   If you need to connect to a new Wi-Fi network with an unknown password, use `iwctl` in the terminal for the initial setup. Once saved, NetworkManager will allow you to toggle connections directly from the notification bar.
2. **Wallpaper Setup:**
   You can change or customize your wallpapers using the **Waypaper** GUI app included in the setup.
3. **Fonts & Emojis:**
   The installer automatically sets up **Google Sans Flex** and core Nerd Fonts. You can install additional emoji packages or custom font pickers according to your preference.

---

## ❤️ Developer Message & Support

Thank you for checking out my dotfiles! If you enjoy this project, please consider leaving a ⭐ on GitHub or dropping a message to show your support:

- 💬 **Telegram:** [+8801829939377](https://t.me/+8801829939377)
- 📸 **Instagram:** [@zakirulzahin](https://instagram.com/zakirulzahin)

*Happy Ricing!* 🚀
