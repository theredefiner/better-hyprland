# ⚡ Better Hyprland v1.0

> **We don't rely on what is defined. We are the Definers.**  
> *A modern, slick, and polished desktop environment experience built for barebones Hyprland on Arch Linux. Powered by a custom PyQt6 native Wayland shell, smooth animations, dynamic taskbar, and a hyper-modern aesthetic.*

---

## ✨ What's New in v1.0 (Changelog)

- **100% Python & PyQt6 Powered**: Built completely from scratch using Python PyQt6 and native Wayland Layer Shell protocol—delivering liquid-smooth UI animations and ultra-responsive floating widgets[cite: 1, 2].
- **Zero Bloat (Stripped Down)**: **Rofi**, **SwayNC**, and **Waybar** have been completely removed! Everything is now handled natively by our custom PyQt6 architecture.
- **Interactive Enhancements**: Integrated live battery charging animations and a dedicated system-wide emoji picker application.
- **Apple Color Emoji Pack**: Pre-configured system-wide Apple Color Emoji font rendering for modern, crisp emoji display across all apps and UI components.
- **Hyper-Modern Theme Hybrid**: A unique blend of **Windows 12 + macOS + Material You** design language, crafted with supreme focus on UI/UX aesthetics.
- **Chocolate Theme Ecosystem**: Includes an all-new Chocolate-themed **Start Menu**, **Side Panel / Quick Settings**, and an **Animated Modern Floating Taskbar**.

---

## 📂 Repository Structure

```text
better-hyprland/
├── better-hyprland/   # Custom PyQt6 Shell modules, Start Menu, Bar & Widgets
├── Fonts/             # Font Awesome 7, Material Symbols & Apple Color Emoji
├── hypr/              # Hyprland Lua scripts & hyprlock configuration
├── kitty/             # Kitty terminal configuration & color theme
├── starship.toml      # Modern Starship prompt configuration
└── install.sh         # One-click installation script
```

## Screenshots:

<img width="1366" height="768" alt="image" src="https://github.com/user-attachments/assets/259677cb-6aff-438a-aaf3-0d835a053d1d" />

<img width="886" height="768" alt="image" src="https://github.com/user-attachments/assets/d2daa33c-a028-44a2-b400-f83aef33f0dd" />

<img width="889" height="603" alt="image" src="https://github.com/user-attachments/assets/4f37ef97-db2a-4192-9bf6-35d8fb4ec6f7" />


## 🛠️ Installation

### 1. Prerequisites
Ensure `git` is installed on your Arch Linux system:
``
sudo pacman -S --needed git
``

### 2. Clone & Run Installer
```
#Clone the repository and execute the installation script:
git clone https://github.com/theredefiner/better-hyprland.git
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
| `Super` + `Space`| Open Emoji picker app

---

## ⚠️ Known Limitations & Notes

1. **Code-Based Theme Customization**:
Currently, you need to directly edit the Python source files inside ~/.config/better-hyprland/ to adjust custom theme values, accent colors, or widget layouts.

---

## ❤️ Developer Message & Support

Thank you for checking out my dotfiles! If you enjoy this project, please consider leaving a ⭐ on GitHub or dropping a message to show your support:

- 💬 **Telegram:** [@Zakirul_zahin](https://t.me/Zakirul_zahin)
- 📸 **Instagram:** [@zakirulzahin](https://instagram.com/zakirulzahin)
- 

*Happy Ricing!* 🚀
