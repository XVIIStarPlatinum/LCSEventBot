# LCSEventBot

[![LCSEventBot CI](https://github.com/XVIIStarPlatinum/LCSEventBot/actions/workflows/challenge-tests.yml/badge.svg)](https://github.com/XVIIStarPlatinum/LCSEventBot/actions/workflows/challenge-tests.yml)

Бот должен публиковать задания в Telegram-группе в топике "Испытания" каждую неделю по понедельникам в 00:00 по МСК. 
Задания делятся на три категории: 
- #АРТИСТ 
- #БИТМЕЙКЕР 
- #ЗВУКОИНЖЕНЕР 

и чередуются в строгом порядке. Бот обеспечивает персистентность данных, уведомления администратора и управление заданиями без повторений в пределах цикла.

This guide is written for whoever will actually run and use the bot day to day ---
no assumed knowledge of servers, Linux, or programming. It covers:

1. Getting a server
2. Downloading and configuring the bot
3. Running it permanently
4. Using the bot day to day (it's fully button-based --- no typing commands)
5. Keeping it running and maintained

It does **not** cover how the code works internally --- that's your developer's
territory. If something here doesn't match what you see, or a command errors
out in a way this guide doesn't explain, that's the moment to loop your
developer back in rather than guessing.

A few terms used throughout, explained once:

- **Server / VPS**: a computer that runs 24/7, rented from a hosting company, so
  the bot doesn't depend on your own laptop being on all the time.
- **SSH**: how you remotely control that server from your own computer, via a
  terminal (a text-based command window).
- **Terminal / command line**: the black-screen, type-commands interface. Every
  boxed line below is something you type (or copy-paste) into it, then press Enter.
- **Repository ("repo")**: the folder containing the bot's code, downloaded from GitHub.

---

## Part 1 --- What you need before starting

- [ ] A server (Part 2 covers getting one if you don't have one yet)
- [ ] A Telegram bot token (Part 2 also covers this)
- [ ] These four values --- you'll paste them into a config file later, so keep
      them handy:
  - `ADMIN_ID` = `...`
  - `GROUP_CHAT_ID` = `...`
  - `TOPIC_ID` = `...`
  - `BOT_TOKEN` = *(you'll get this fresh from BotFather below --- it's a secret,
    treat it like a password)*

---

## Part 2 --- Getting a server and a bot token

### 2.1 Renting a server

If you don't already have one: any of **Hetzner**, **DigitalOcean**, or
**Vultr** work fine for this --- the bot is lightweight, so their cheapest tier
(around $4–6/month) is more than enough. When creating the server, choose:

- **Ubuntu 22.04 or 24.04** as the operating system
- The smallest/cheapest size available

The provider will give you a server IP address (a set of numbers like
`123.45.67.89`) and either a root password or an SSH key. Keep that
information somewhere safe --- you'll need it in the next step.

### 2.2 Connecting to your server

- **On Mac or Linux**: open the Terminal app and run:
  ```
  ssh root@YOUR_SERVER_IP
  ```
- **On Windows**: use Windows Terminal or PowerShell with the same command
  above, or a tool like PuTTY if your provider recommends it.

Replace `YOUR_SERVER_IP` with the actual address. The first time, it'll ask if
you trust this connection --- type `yes`. Then enter the password if prompted.
You're now controlling the server, not your own computer.

### 2.3 Getting a Telegram bot token (if you don't already have one)

Skip this if your developer already gave you a working `BOT_TOKEN`.

1. In Telegram, message **@BotFather**.
2. Send `/newbot` and follow the prompts (it'll ask for a name and a username
   ending in `bot`).
3. BotFather replies with a long token like `123456789:ABCdefGhIJKlmNoPQRstuVwxyz`.
   That's your `BOT_TOKEN` --- copy it somewhere safe. Anyone who has it can
   control your bot, so don't post it publicly or commit it to GitHub.

---

## Part 3 --- Installing prerequisites on the server

Once connected via SSH, run these one at a time (each line, then Enter):

```
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git
```

This updates the server and installs Python, its package manager, and Git
(the tool used to download the bot's code). This takes a couple of minutes.

---

## Part 4 --- Downloading the bot's code

```
git clone https://github.com/XVIIStarPlatinum/LCSEventBot.git
cd LCSEventBot
```

You're now inside the bot's folder. Everything from here on assumes you're
still in this folder --- if you disconnect and reconnect later, run `cd LCSEventBot`
again first.

---

## Part 5 --- Setting up the Python environment

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

What this does: creates an isolated Python environment just for this bot
(`.venv`), switches into it, then installs everything the bot needs to run.
This install also pulls in a few developer tools (code formatters, test
runners) alongside the actual bot dependencies --- that's expected and harmless,
just not perfectly tidy.

You'll know it worked if the last few lines mention `Successfully installed`.

---

## Part 6 --- Configuring the bot

The bot reads its settings from a file called `.env`. Create it from the template:

```
cp .env.example .env
nano .env
```

`nano` opens a simple text editor right in the terminal. Edit the file so it
looks like this (replace `PASTE_YOUR_TOKEN_HERE` with the real token from
Part 2.3):

```
BOT_TOKEN=...
ADMIN_ID=...
GROUP_CHAT_ID=...
TOPIC_ID=...
```

**Important**: delete the `STATE_FILE=...` and `TIMEZONE=...` lines entirely
(or leave them completely blank) rather than leaving the `...` placeholder ---
the bot treats a real value of literal `...` as if you'd deliberately chosen
it, not as "unset." Leaving them out entirely is what makes the bot fall back
to its sensible defaults (a file called `tasks_state.json`, and `Europe/Moscow`
for the weekly schedule). Only add these back in if you specifically want a
different filename or timezone.

To save and exit `nano`: press `Ctrl+O`, then `Enter`, then `Ctrl+X`.

---

## Part 7 --- Test-running it manually first

Before setting it up to run permanently, make sure it actually starts cleanly:

```
python3 bot.py
```

You should see log lines and no errors, and the process will just sit there
running (that's correct --- it's now live and listening). In Telegram, message
your bot with `/start` (or tap the **Start** button Telegram shows
automatically the first time you open a chat with it). You should get a reply
with three menu buttons. If that works, press `Ctrl+C` in the terminal to stop
it, and move to the next part to make it run permanently.

If you get an error instead --- especially anything mentioning `BOT_TOKEN`,
`ADMIN_ID`, `GROUP_CHAT_ID`, or `TOPIC_ID` --- it's almost always a typo in the
`.env` file from Part 6. Re-check it with `nano .env`.

---

## Part 8 --- Running it permanently (so it survives reboots and disconnects)

Right now, the bot only runs while your terminal is open. We'll use
**systemd** (Ubuntu's built-in tool for managing background services) so it
starts automatically, restarts itself if it ever crashes, and survives server
reboots.

First, find the full path to your bot folder --- while still inside it, run:

```
pwd
```

This prints something like `/root/LCSEventBot` or `/home/yourname/LCSEventBot`
--- note it down, you'll need it below.

Create the service file:

```
sudo nano /etc/systemd/system/lcseventbot.service
```

Paste this in (using the same `nano` save/exit as before: `Ctrl+O`, `Enter`,
`Ctrl+X`). Replace **every** `/root/LCSEventBot` below with the path `pwd`
gave you, and `root` with your actual username if different:

```ini
[Unit]
Description=LCSEventBot Telegram bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/LCSEventBot
ExecStart=/root/LCSEventBot/.venv/bin/python3 bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then enable and start it:

```
sudo systemctl daemon-reload
sudo systemctl enable lcseventbot
sudo systemctl start lcseventbot
```

Check it's actually running:

```
sudo systemctl status lcseventbot
```

You should see `active (running)` in green. Message the bot in Telegram again
to confirm it responds. From now on, the bot runs continuously in the
background --- you can close your terminal and it keeps going, and it'll start
itself automatically if the server ever reboots.

---

## Part 9 --- Seeding your first tasks (don't skip this)

The bot starts with **zero** tasks in every category. If you don't add any
before the next Monday, the automatic weekly publish will simply have nothing
to post. Before relying on it:

1. Message the bot, tap **➕ Добавить задание**.
2. Pick a category.
3. Send the task text.
4. Repeat for as many tasks as you want in each category --- the more you add
   up front, the longer the bot can run before it cycles back through them.

You can always add more later; there's no need to load everything on day one.

---

## Part 10 --- Using the bot day to day

Everything is button-driven --- you never type a command except the very first
`/start` (and Telegram handles that one for you with its own **Start** button).
Only the Telegram account with your ID can use any of this; anyone
else who messages the bot is silently ignored.

After `/start`, you'll always see three buttons at the bottom of the chat:

- **➕ Добавить задание** --- add a new task. Pick a category, then send the task
  text as a normal message. There's a cancel option at every step if you
  change your mind partway through.
- **📢 Опубликовать** --- manually publish a task right now (outside the normal
  Monday schedule), with a confirm/cancel step before anything actually posts.
- **📋 Список заданий** --- browse tasks. Pick a category (or **ВСЕ** to see all
  categories at once), then pick which list: **Все** (everything ever added),
  **Доступные** (not yet used this cycle), or **Использованные** (already
  used this cycle). There's a button to go back and look at something else
  without starting over.

Separately, every **Monday at 00:00 Moscow time**, the bot automatically picks
and publishes the next task on its own --- no action needed from you for that
to happen, as long as the bot is running (Part 8) and there are tasks
available (Part 9).

---

## Part 11 --- Quick health check after any change

Whenever you set this up fresh, or after an update, it's worth a two-minute check:

1. `sudo systemctl status lcseventbot` → should say `active (running)`.
2. Message the bot `/start` → menu appears.
3. Add one test task via the menu.
4. Tap **📢 Опубликовать**, confirm → check the message shows up (and gets
   pinned) in the actual Telegram group/topic, and that you get a DM
   confirmation.
5. Tap **📋 Список заданий** → confirm your test task shows up in the right
   category.

If all five pass, you're good.

---

## Part 12 --- Ongoing maintenance

**Check if it's running:**
```
sudo systemctl status lcseventbot
```

**View recent logs** (useful if something seems off):
```
journalctl -u lcseventbot -n 100
```
Add `-f` to the end (`journalctl -u lcseventbot -f`) to watch logs live as
they happen --- press `Ctrl+C` to stop watching.

**Restart it** (rarely needed --- systemd restarts it automatically if it
crashes --- but useful after config changes):
```
sudo systemctl restart lcseventbot
```

**Stop it** (if you need to take it down deliberately):
```
sudo systemctl stop lcseventbot
```

**Updating to newer code** (once your developer has pushed changes):
```
cd /root/LCSEventBot
git pull
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart lcseventbot
```
Then run through the Part 11 health check again.

**Backing up your task data**: everything the bot knows (all tasks, what's
available, what's used) lives in one file, `tasks_state.json`, inside the bot
folder. It's worth copying it somewhere safe occasionally:
```
cp tasks_state.json tasks_state.backup-$(date +%F).json
```
Consider downloading a copy off the server entirely every so often (e.g. via
`scp` from your own computer, or just asking your developer to set up an
automated backup) --- if the server is ever lost, this file is the only thing
that isn't recoverable from GitHub.

---

## Part 13 --- Troubleshooting

| Symptom                                           | Likely cause / what to do                                                                                                                                                |
|---------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Bot doesn't reply to `/start` at all              | Check `sudo systemctl status lcseventbot` --- if it's not `active`, check logs (`journalctl -u lcseventbot -n 50`) for the reason, usually a `.env` typo                 |
| "Установите переменную окружения ..." in the logs | A required value is missing or malformed in `.env` --- re-check Part 6                                                                                                   |
| Bot replies to some buttons but not others        | Restart it (`sudo systemctl restart lcseventbot`) --- if it persists, this is a code question for your developer, not a deployment one                                   |
| Nothing gets published on Monday                  | Check you actually added tasks (Part 9), and that the bot was running at 00:00 Monday Moscow time --- it won't retroactively publish if it was down at that exact moment |
| You changed `.env` but nothing changed            | `.env` is only read when the bot starts --- you must `sudo systemctl restart lcseventbot` after any edit                                                                 |
| Server rebooted and bot didn't come back          | Confirm you ran `sudo systemctl enable lcseventbot` in Part 8 --- `start` alone doesn't survive a reboot, `enable` does                                                  |

---

## Part 14 --- Basic security notes

- Never share your `BOT_TOKEN` or paste it into chat, forums, or screenshots.
- The `.env` file is already excluded from GitHub uploads (via `.gitignore`),
  so updating the code (`git pull`) won't touch or expose it.
- Keep the server itself updated occasionally: `sudo apt update && sudo apt upgrade -y`.
- If you ever suspect the token was exposed, message @BotFather, use
  `/revoke` on the bot, generate a new token, and update it in `.env`
  (then restart the service).

---

## Quick reference

```
# Status / logs / control
sudo systemctl status lcseventbot
journalctl -u lcseventbot -f
sudo systemctl restart lcseventbot
sudo systemctl stop lcseventbot

# Updating the code
cd /root/LCSEventBot && git pull && source .venv/bin/activate && pip install -r requirements.txt && sudo systemctl restart lcseventbot

# Backing up task data
cp tasks_state.json tasks_state.backup-$(date +%F).json
```
