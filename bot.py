import telebot
import random
import sqlite3
import time

token = "8662662764:AAFG7KLiNg6L94I56E7PZ5KCLrMlhygiDh4"
bot = telebot.TeleBot(token)

def db():
    conn = sqlite3.connect('db.db')
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS user(
    id INTEGER PRIMARY KEY,
    size INTEGER,
    name TEXT,
    last_play INTEGER
    )
    """)
    conn.commit()
    conn.close()

db()

@bot.message_handler(commands=['dick'])
def dick(message):
    random_num = random.randint(-5, 10)
    conn = sqlite3.connect('db.db')
    cur = conn.cursor()
    
    cur.execute("SELECT size, last_play FROM user WHERE id=?", (message.from_user.id,))
    row = cur.fetchone()

    now = int(time.time())
    day = 86400

    if row is None:
        size = random_num
        cur.execute(
            "INSERT INTO user (id, size, name, last_play) VALUES (?, ?, ?, ?)",
            (message.from_user.id, size, message.from_user.first_name, now)
        )
    else:
        size, last_play = row
        if now - last_play < day:
            bot.send_message(message.chat.id, "Ty už jsi dnes hrál!")
            conn.close()
            return

        size += random_num
        cur.execute(
            "UPDATE user SET size=?, last_play=?, name=? WHERE id=?",
            (size, now, message.from_user.first_name, message.from_user.id)
        )

    # Výpočet pořadí v topu
    cur.execute("SELECT id FROM user ORDER BY size DESC")
    rows = cur.fetchall()

    place = 1
    for r in rows:
        if r[0] == message.from_user.id:
            break
        place += 1

    bot.send_message(
        message.chat.id,
        f'<a href="tg://user?id={message.from_user.id}">{message.from_user.first_name}</a>, tvůj výsledek se změnil o <b>{random_num}</b> cm.\n'
        f'Teď máš <b>{size}</b> cm.\n'
        f'Jsi na <b>{place}.</b> místě v žebříčku.\n'
        f'Další pokus zítra!',
        parse_mode="HTML"
    )

    conn.commit()
    conn.close()

@bot.message_handler(commands=['top_dick'])
def top_dick(message):
    conn = sqlite3.connect('db.db')
    cur = conn.cursor()
    cur.execute("SELECT name, size FROM user ORDER BY size DESC LIMIT 10")
    rows = cur.fetchall()
    conn.close()

    text = "Top 10 hráčů 🔝\n\n"

    for i, (name, size) in enumerate(rows, start=1):
        if i == 1:
            text += f"👑 {i} | <b>{name}</b> — {size} cm\n"
        else:
            text += f"{i} | {name} — {size} cm\n"

    bot.send_message(message.chat.id, text, parse_mode="HTML")

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id,
        "Ahoj! Jsem bot pravítko 📏\n\n"
        "/dick — změnit velikost\n"
        "/top_dick — top hráčů")

@bot.message_handler(commands=['help'])
def help(message):
    bot.send_message(message.chat.id,
        "Příkazy:\n"
        "/dick — změnit velikost\n"
        "/top_dick — top hráčů")

if __name__ == "__main__":
    bot.polling(none_stop=True)