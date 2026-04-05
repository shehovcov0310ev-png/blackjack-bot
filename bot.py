import logging
import random
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ========== ТОКЕН (ЧЕРЕЗ ПЕРЕМЕННУЮ ОКРУЖЕНИЯ) ==========
TOKEN = os.environ.get("TELEGRAM_TOKEN", "8604841967:AAFaclZhctIxD4DRIHWKT55giRVgBW5LOBo")

logging.basicConfig(level=logging.INFO)

# ========== ХРАНИЛИЩА ==========
lobbies = {}
games = {}
stats = {}

# ========== ФУНКЦИИ КАРТ ==========
def get_deck():
    suits = ["♥", "♦", "♣", "♠"]
    ranks = ["6", "7", "8", "9", "10", "J", "Q", "K", "A"]
    deck = []
    for s in suits:
        for r in ranks:
            if r in ["J", "Q", "K"]:
                value = 10
            elif r == "A":
                value = 11
            else:
                value = int(r)
            deck.append({"rank": r, "suit": s, "value": value})
    random.shuffle(deck)
    return deck

def calc_score(cards):
    score = sum(c["value"] for c in cards)
    aces = sum(1 for c in cards if c["rank"] == "A")
    while score > 21 and aces > 0:
        score -= 10
        aces -= 1
    return score

def cards_str(cards):
    return " ".join(f"{c['rank']}{c['suit']}" for c in cards)

# ========== КОМАНДЫ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🃏 *Блэкджек бот*\n\n"
        "/bj - создать лобби\n"
        "/join - присоединиться\n"
        "/startgame - начать игру (только создатель)\n"
        "/top - топ побед\n"
        "/endgame - завершить игру",
        parse_mode="Markdown"
    )

async def bj(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name

    if chat_id in lobbies:
        await update.message.reply_text("❌ Лобби уже есть!")
        return

    lobbies[chat_id] = {
        "owner": user_id,
        "players": [user_id],
        "active": False
    }

    keyboard = [[InlineKeyboardButton("🔥 Присоединиться", callback_data="join")]]
    await update.message.reply_text(
        f"🎲 *Лобби создано!*\n👑 Создатель: {user_name}\n👥 Игроков: 1",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name

    if chat_id not in lobbies:
        await update.message.reply_text("❌ Нет лобби! /bj")
        return

    lobby = lobbies[chat_id]
    if user_id in lobby["players"]:
        await update.message.reply_text("⚠️ Ты уже в лобби!")
        return

    lobby["players"].append(user_id)
    await update.message.reply_text(f"✅ {user_name} присоединился! 👥 {len(lobby['players'])} игроков")

async def startgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if chat_id not in lobbies:
        await update.message.reply_text("❌ Нет лобби!")
        return

    lobby = lobbies[chat_id]
    if user_id != lobby["owner"]:
        await update.message.reply_text("❌ Только создатель!")
        return
    if len(lobby["players"]) < 2:
        await update.message.reply_text("❌ Нужно минимум 2 игрока!")
        return

    lobby["active"] = True

    deck = get_deck()
    players_cards = {}
    for p in lobby["players"]:
        players_cards[p] = [deck.pop(), deck.pop()]
    dealer_cards = [deck.pop(), deck.pop()]

    games[chat_id] = {
        "deck": deck,
        "players_cards": players_cards,
        "dealer_cards": dealer_cards,
        "turn_index": 0,
        "player_order": lobby["players"].copy()
    }

    await update.message.reply_text("🃏 *Игра началась!*", parse_mode="Markdown")
    await send_turn(chat_id, context)

async def send_turn(chat_id, context):
    game = games[chat_id]
    idx = game["turn_index"]
    player_id = game["player_order"][idx]
    cards = game["players_cards"][player_id]
    score = calc_score(cards)

    keyboard = [
        [InlineKeyboardButton("🃏 Взять карту", callback_data="hit")],
        [InlineKeyboardButton("✋ Хватит", callback_data="stay")]
    ]

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"🎯 *Твой ход!*\n🎴 {cards_str(cards)}\n📊 Очки: {score}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def hit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    user_id = query.from_user.id

    if chat_id not in games:
        await query.edit_message_text("❌ Нет активной игры!")
        return

    game = games[chat_id]
    current_id = game["player_order"][game["turn_index"]]
    if user_id != current_id:
        await query.answer("Сейчас не твой ход!", show_alert=True)
        return

    new_card = game["deck"].pop()
    game["players_cards"][user_id].append(new_card)
    score = calc_score(game["players_cards"][user_id])

    if score > 21:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"💥 *ПЕРЕБОР!*\n🎴 {cards_str(game['players_cards'][user_id])}\n📊 Очки: {score}\n\n❌ Ты выбываешь",
            parse_mode="Markdown"
        )
        game["turn_index"] += 1

        if game["turn_index"] >= len(game["player_order"]):
            await endgame(chat_id, context, update)
        else:
            await send_turn(chat_id, context)
    else:
        keyboard = [
            [InlineKeyboardButton("🃏 Взять карту", callback_data="hit")],
            [InlineKeyboardButton("✋ Хватит", callback_data="stay")]
        ]
        await query.edit_message_text(
            text=f"✅ Взял карту!\n\n🎯 *Твой ход*\n🎴 {cards_str(game['players_cards'][user_id])}\n📊 Очки: {score}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def stay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    user_id = query.from_user.id

    if chat_id not in games:
        await query.edit_message_text("❌ Нет активной игры!")
        return

    game = games[chat_id]
    current_id = game["player_order"][game["turn_index"]]
    if user_id != current_id:
        await query.answer("Сейчас не твой ход!", show_alert=True)
        return

    score = calc_score(game["players_cards"][user_id])
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"✋ {update.effective_user.first_name} остановился с {score} очками"
    )

    game["turn_index"] += 1

    if game["turn_index"] >= len(game["player_order"]):
        await endgame(chat_id, context, update)
    else:
        await send_turn(chat_id, context)

async def endgame(chat_id, context, update=None):
    game = games[chat_id]

    dealer_cards = game["dealer_cards"]
    while calc_score(dealer_cards) < 17:
        dealer_cards.append(game["deck"].pop())
    dealer_score = calc_score(dealer_cards)

    result = f"🃏 *РЕЗУЛЬТАТ ИГРЫ* 🃏\n\n🤖 *Диллер:* {cards_str(dealer_cards)} = {dealer_score}\n\n"

    for player_id in game["player_order"]:
        cards = game["players_cards"][player_id]
        score = calc_score(cards)
        result += f"👤 *Игрок:* {cards_str(cards)} = {score}"

        if score > 21:
            result += " (ПЕРЕБОР) ❌\n"
        elif dealer_score > 21 or score > dealer_score:
            result += " — ПОБЕДА! ✅\n"
            if chat_id not in stats:
                stats[chat_id] = {}
            if player_id not in stats[chat_id]:
                # Попробуем получить имя через update, если оно доступно
                user_name = "Неизвестный"
                if update and update.effective_user and update.effective_user.id == player_id:
                    user_name = update.effective_user.first_name
                
                stats[chat_id][player_id] = {"name": user_name, "wins": 0}
            stats[chat_id][player_id]["wins"] += 1
        elif score == dealer_score:
            result += " (НИЧЬЯ) 🤝\n"
        else:
            result += " (ПРОИГРЫШ) ❌\n"

    await context.bot.send_message(chat_id=chat_id, text=result, parse_mode="Markdown")

    if chat_id in games: del games[chat_id]
    if chat_id in lobbies: del lobbies[chat_id]

async def cmd_endgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if chat_id not in lobbies:
        await update.message.reply_text("❌ Нет активной игры!")
        return

    if user_id != lobbies[chat_id]["owner"]:
        await update.message.reply_text("❌ Только создатель!")
        return

    if chat_id in games:
        del games[chat_id]
    del lobbies[chat_id]

    await update.message.reply_text("⛔ *Игра завершена создателем!*", parse_mode="Markdown")

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if chat_id not in stats or not stats[chat_id]:
        await update.message.reply_text("🏆 Пока нет побед!")
        return

    top_list = sorted(stats[chat_id].items(), key=lambda x: x[1]["wins"], reverse=True)[:10]

    text = "🏆 *Топ побед в чате:*\n\n"
    for i, (uid, data) in enumerate(top_list, 1):
        name = data["name"]
        wins = data["wins"]
        text += f"{i}. {name} — {wins} 🏅\n"

    await update.message.reply_text(text, parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == "join":
        await join(update, context)
    elif data == "hit":
        await hit(update, context)
    elif data == "stay":
        await stay(update, context)

    await query.answer()

# ========== ЗАПУСК ==========
def main():
    if not TOKEN:
        print("❌ Error: TELEGRAM_TOKEN or hardcoded TOKEN not found.")
        return
        
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("bj", bj))
    app.add_handler(CommandHandler("join", join))
    app.add_handler(CommandHandler("startgame", startgame))
    app.add_handler(CommandHandler("endgame", cmd_endgame))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("✅ Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
