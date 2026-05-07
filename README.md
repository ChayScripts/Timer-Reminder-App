# Timer & Reminder App

A Windows desktop app built with Python that combines reminders, countdown timers, custom notification sounds, system tray support, and Windows toast notifications in a modern UI.

## Features

* One-time reminders
* Recurring reminders:
  * Daily
  * Weekdays
  * Weekends
  * Weekly
* Live countdown for reminders
* Countdown timer
* Custom MP3 notification sounds
* Windows toast notifications
* System tray minimize support
* Automatic saving of reminders and settings

## Installation

```bash
git clone https://github.com/yourusername/timer-reminder.git
cd timer-reminder
pip install -r requirements.txt
```

## Run

```bash
python app.py
```

## Build EXE

```bash
pip install pyinstaller
```

```bash
pyinstaller.exe --onefile --windowed --icon=app_icon.ico --name="Timer Reminder" --add-data "app_icon.ico;." app.py
```

Generated executable:

```bash
dist/Timer Reminder.exe
```

## Project Structure

```bash
timer-reminder/
├── app.py
├── app_icon.ico
├── config.json
├── reminders.json
└── requirements.txt
```

## Dependencies

* CustomTkinter
* Pygame
* PyInstaller
* pystray
* Pillow
* Windows toast notifications

## License

MIT
