import telebot
import random
import sqlite3
import time
from flask import Flask
from threading import Thread

token = "8662662764:AAFG7KLiNg6L94I56E7PZ5KCLrMlhygiDh4"
bot = telebot.TeleBot(token)

# ── Keep-alive server (pro Replit) ─────────────────────────────────────────────
app = Flask('')


@app.route('/')
def home():
    return "OK"


def run():
    app.run(host='0.0.0.0', port=8080)


def keep_alive():
    t = Thread(target=run)
    t.start()


# ── Databáze ───────────────────────────────────────────────────────────────────
def db():
    conn = sqlite3.connect('db.db')
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS user
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY,
                       size
                       INTEGER,
                       name
                       TEXT,
                       last_play
                       INTEGER
                   )""")
    conn.commit()
    conn.close()


db()


# ── Příkazy ────────────────────────────────────────────────────────────────────
@bot.message_handler(commands=['top_dick'])
def top_dick(message):
    conn = sqlite3.connect('db.db')
    cur = conn.cursor()
    cur.execute("SELECT name, size FROM user ORDER BY size DESC LIMIT 10")
    row = cur.fetchall()
    text = "Топ 10 игроков 🔝 \n\n"

    for num, users in enumerate(row):
        a = len(row)
        user = users
        if num == 0:
            text += f"{num + 1}|{user[0]} 🍆 - {user[1]} cm \n"
        elif num > a:
            text += f"{num + 1}|{user[0]} 🤥 <b>хуйня</b> - {user[1]} cm \n"
        else:
            text += f"{num + 1}|{user[0]} - {user[1]} cm \n"

    bot.send_message(message.chat.id, text, parse_mode='HTML')
    conn.close()


@bot.message_handler(commands=['dick'])
def dick(message):
    random_num = random.randint(-1, 15)
    conn = sqlite3.connect('db.db')
    cur = conn.cursor()
    cur.execute("SELECT size, last_play FROM user WHERE id=?", (message.from_user.id,))
    row = cur.fetchone()

    now = int(time.time())
    day = 86400

    if row is None:
        size = random_num
        cur.execute("INSERT INTO user VALUES (?, ?, ?, ?)",
                    (message.from_user.id, size, message.from_user.first_name, now))
        bot.send_message(message.chat.id,
                         f"""<a href="tg://user?id={message.from_user.id}">{message.from_user.first_name}</a>, твой писюн вырос на <b>{random_num}</b> см.
Теперь он равен <b>{size}</b> см.
Следующая попытка завтра!""", parse_mode='HTML')
    else:
        cur.execute("SELECT id FROM user ORDER BY size DESC")
        rows = cur.fetchall()
        place = 1
        for r in rows:
            if r[0] == message.from_user.id:
                break
            place += 1

        size, last_play = row

        if now - last_play < day:
            bot.send_message(message.chat.id,
                             f"""<a href="tg://user?id={message.from_user.id}">{message.from_user.first_name}</a>, ты уже играл.
Сейчас он равен {size} см.
Ты занимаешь {place} место в топе.
Следующая попытка завтра!""", parse_mode='HTML')
            conn.close()
            return

        size = size + random_num
        cur.execute("UPDATE user SET size=?, last_play=? WHERE id=?", (size, now, message.from_user.id))
        bot.send_message(message.chat.id,
                         f"""<a href="tg://user?id={message.from_user.id}">{message.from_user.first_name}</a>, твой писюн вырос на <b>{random_num}</b> см.
Теперь он равен <b>{size}</b> см.
Ты занимаешь <b>{place}</b> место в топе.
Следующая попытка завтра!""", parse_mode='HTML')

    conn.commit()
    conn.close()


@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, """Привет! я линейка — бот для чатов (групп)

Смысл бота: бот работает только в чатах. Раз
в 24 часа игрок может прописать команду
/dick, где в ответ получит от бота рандомное
число.
Рандом работает от -5 см до +10 см.

Если у тебя есть вопросы — пиши команду: /help
""")


@bot.message_handler(commands=['help'])
def help(message):
    bot.send_message(message.chat.id, """Команды бота:
/dick — Вырастить/уменьшить пипису
/top_dick — Топ 10 пипис чата

Контакты:
Наш канал — @slv299
Наш чат — сбор хуйни и картинки""")


@bot.message_handler(commands=['zbor'])
def zbor(message):
    conn = sqlite3.connect("db.db")
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM user")
    players = cur.fetchall()
    conn.close()

    text = "АЛООУУУ СУЕТА 🔔\n"
    for uid, name in players:
        text += f'<a href="tg://user?id={uid}">{name}</a> \n'

    bot.send_message(message.chat.id, text, parse_mode="HTML")


# ── Start ──────────────────────────────────────────────────────────────────────
keep_alive()
bot.infinity_polling()