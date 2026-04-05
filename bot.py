import logging
import random
import os
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import pytz  # ДОБАВИТЬ ЭТУ БИБЛИОТЕКУ

# ========== ТОКЕН ИЗ ПЕРЕМЕННОЙ ОКРУЖЕНИЯ ==========
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("Добавь TELEGRAM_BOT_TOKEN в переменные окружения")

logging.basicConfig(level=logging.INFO)

# ========== ХРАНИЛИЩА ==========
lobbies = {}
games = {}
stats = {}        # stats[chat_id][user_id] = {"name": str, "wins": int, "total_wins": int}
last_messages = {}

# ========== ФУНКЦИЯ ПОЛУЧЕНИЯ ИМЕНИ ==========
def get_user_name(user):
    if user.username:
        return f"@{user.username}"
    if user.first_name:
        return user.first_name
    return "Игрок"

# ========== ФУНКЦИИ КАРТ ==========
def get_deck():
    suits = ["♥", "♦", "♣", "♠"]
    ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
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

async def delete_previous_message(chat_id, context):
    if chat_id in last_messages:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=last_messages[chat_id])
        except:
            pass
        del last_messages[chat_id]

# ========== АВТОСБРОС ТОПА КАЖДОЕ ВОСКРЕСЕНЬЕ В 23:59 МСК ==========
async def weekly_reset(context: ContextTypes.DEFAULT_TYPE):
    """Сбрасывает недельные победы, обновляет общий счёт"""
    global stats
    
    for chat_id in stats:
        for user_id in stats[chat_id]:
            # Добавляем недельные победы к общим
            stats[chat_id][user_id]["total_wins"] = stats[chat_id][user_id].get("total_wins", 0) + stats[chat_id][user_id]["wins"]
            # Сбрасываем недельные
            stats[chat_id][user_id]["wins"] = 0
    
    # Уведомляем все чаты
    for chat_id in stats:
        await context.bot.send_message(
            chat_id=chat_id,
            text="🎉 *Новая неделя побед!* 🎉\n\nПобеждай и становись лидером этой недели! 🥳",
            parse_mode="Markdown"
        )

# ========== КОМАНДЫ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🃏 *Блэкджек бот*\n\n"
        "🎲 `/bj` — создать лобби\n"
        "➕ `/join` — присоединиться\n"
        "▶️ `/startgame` — начать игру (только создатель)\n"
        "🏆 `/top` — глобальный топ\n"
        "👤 `/profile` — твой профиль\n"
        "⛔ `/endgame` — завершить игру (только создатель)",
        parse_mode="Markdown"
    )

async def bj(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_name = get_user_name(update.effective_user)

    if chat_id in lobbies:
        await update.message.reply_text("❌ Лобби уже есть!")
        return

    lobbies[chat_id] = {
        "owner": user_id,
        "players": [user_id],
        "active": False
    }

    await update.message.reply_text(
        f"🎲 *Лобби создано!*\n👑 Создатель: {user_name}\n👥 Игроков: 1\n\n📢 Другие игроки, введите `/join` чтобы присоединиться!",
        parse_mode="Markdown"
    )

async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_name = get_user_name(update.effective_user)

    if chat_id not in lobbies:
        await update.message.reply_text("❌ Нет лобби! Создайте /bj")
        return

    lobby = lobbies[chat_id]
    if lobby.get("active", False):
        await update.message.reply_text("❌ Игра уже идёт!")
        return

    if user_id in lobby["players"]:
        await update.message.reply_text("⚠️ Ты уже в лобби!")
        return

    lobby["players"].append(user_id)
    
    # Собираем имена всех игроков
    players_list = []
    for pid in lobby["players"]:
        try:
            p = await context.bot.get_chat(pid)
            players_list.append(get_user_name(p))
        except:
            players_list.append("Игрок")
    
    await update.message.reply_text(
        f"✅ {user_name} присоединился!\n👥 Игроков: {len(lobby['players'])}\n📋 В лобби: {', '.join(players_list)}"
    )

async def startgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if chat_id not in lobbies:
        await update.message.reply_text("❌ Нет лобби!")
        return

    lobby = lobbies[chat_id]
    if user_id != lobby["owner"]:
        await update.message.reply_text("❌ Только создатель может начать игру!")
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

    try:
        player = await context.bot.get_chat(player_id)
        player_name = get_user_name(player)
    except:
        player_name = "Игрок"

    keyboard = [
        [InlineKeyboardButton("🃏 Взять карту", callback_data="hit")],
        [InlineKeyboardButton("✋ Хватит", callback_data="stay")]
    ]

    await delete_previous_message(chat_id, context)

    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"🎯 *Ход игрока {player_name}!*\n\n🎴 Твои карты: {cards_str(cards)}\n📊 Очки: {score}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    last_messages[chat_id] = msg.message_id

async def hit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    user_id = query.from_user.id

    await delete_previous_message(chat_id, context)

    if chat_id not in games:
        await context.bot.send_message(chat_id=chat_id, text="❌ Нет активной игры!")
        return

    game = games[chat_id]
    current_id = game["player_order"][game["turn_index"]]
    if user_id != current_id:
        await context.bot.send_message(chat_id=chat_id, text="⏳ Сейчас не твой ход!")
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
            await endgame(chat_id, context)
        else:
            await send_turn(chat_id, context)
    else:
        keyboard = [
            [InlineKeyboardButton("🃏 Взять карту", callback_data="hit")],
            [InlineKeyboardButton("✋ Хватит", callback_data="stay")]
        ]
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ Взял карту!\n\n🎴 {cards_str(game['players_cards'][user_id])}\n📊 Очки: {score}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        last_messages[chat_id] = msg.message_id

async def stay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    user_id = query.from_user.id

    await delete_previous_message(chat_id, context)

    if chat_id not in games:
        await context.bot.send_message(chat_id=chat_id, text="❌ Нет активной игры!")
        return

    game = games[chat_id]
    current_id = game["player_order"][game["turn_index"]]
    if user_id != current_id:
        await context.bot.send_message(chat_id=chat_id, text="⏳ Сейчас не твой ход!")
        return

    score = calc_score(game["players_cards"][user_id])
    
    try:
        player = await context.bot.get_chat(user_id)
        player_name = get_user_name(player)
    except:
        player_name = "Игрок"
    
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"✋ {player_name} остановился с {score} очками"
    )

    game["turn_index"] += 1

    if game["turn_index"] >= len(game["player_order"]):
        await endgame(chat_id, context)
    else:
        await send_turn(chat_id, context)

async def endgame(chat_id, context):
    game = games[chat_id]

    dealer_cards = game["dealer_cards"]
    while calc_score(dealer_cards) < 17:
        dealer_cards.append(game["deck"].pop())
    dealer_score = calc_score(dealer_cards)

    result = f"🃏 *РЕЗУЛЬТАТ ИГРЫ* 🃏\n\n🤖 *Диллер:* {cards_str(dealer_cards)} = {dealer_score}\n\n"

    for player_id in game["player_order"]:
        cards = game["players_cards"][player_id]
        score = calc_score(cards)
        
        try:
            player = await context.bot.get_chat(player_id)
            player_name = get_user_name(player)
        except:
            player_name = "Игрок"
        
        result += f"👤 *{player_name}:* {cards_str(cards)} = {score}"

        if score > 21:
            result += " (ПЕРЕБОР) ❌\n"
        elif dealer_score > 21 or score > dealer_score:
            result += " — ПОБЕДА! ✅\n"
            
            # Сохраняем победу
            if chat_id not in stats:
                stats[chat_id] = {}
            if player_id not in stats[chat_id]:
                stats[chat_id][player_id] = {"name": player_name, "wins": 0, "total_wins": 0}
            stats[chat_id][player_id]["wins"] += 1
            stats[chat_id][player_id]["name"] = player_name
            
        elif score == dealer_score:
            result += " (НИЧЬЯ) 🤝\n"
        else:
            result += " (ПРОИГРЫШ) ❌\n"

    await context.bot.send_message(chat_id=chat_id, text=result, parse_mode="Markdown")

    del games[chat_id]
    del lobbies[chat_id]
    if chat_id in last_messages:
        del last_messages[chat_id]

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
    if chat_id in last_messages:
        del last_messages[chat_id]

    await update.message.reply_text("⛔ *Игра завершена создателем!*", parse_mode="Markdown")

# ========== ГЛОБАЛЬНЫЙ ТОП (по всем чатам) ==========
async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Собираем всех игроков из всех чатов
    global_players = {}
    
    for chat_id in stats:
        for user_id, data in stats[chat_id].items():
            if user_id not in global_players:
                global_players[user_id] = {"name": data["name"], "wins": 0}
            global_players[user_id]["wins"] += data["wins"]
    
    if not global_players:
        await update.message.reply_text("🏆 Пока нет побед! Сыграйте партию.")
        return
    
    top_list = sorted(global_players.items(), key=lambda x: x[1]["wins"], reverse=True)[:10]
    
    text = "🌍 *ГЛОБАЛЬНЫЙ ТОП* 🌍\n\n"
    for i, (uid, data) in enumerate(top_list, 1):
        text += f"{i}. {data['name']} — {data['wins']} 🏅\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

# ========== ПРОФИЛЬ ИГРОКА ==========
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = get_user_name(update.effective_user)
    
    # Собираем статистику по всем чатам
    total_wins = 0
    weekly_wins = 0
    
    for chat_id in stats:
        if user_id in stats[chat_id]:
            weekly_wins += stats[chat_id][user_id].get("wins", 0)
            total_wins += stats[chat_id][user_id].get("total_wins", 0)
    
    text = (
        f"👤 *Профиль игрока*\n\n"
        f"📛 Имя: {user_name}\n"
        f"🏅 Побед на этой неделе: {weekly_wins}\n"
        f"🏆 Всего побед за всё время: {total_wins}\n\n"
        f"✨ Играй больше, чтобы попасть в глобальный топ!"
    )
    
    await update.message.reply_text(text, parse_mode="Markdown")

# ========== ОБРАБОТЧИК КНОПОК ==========
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
    
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "hit":
        await hit(update, context)
    elif data == "stay":
        await stay(update, context)

# ========== ЗАПУСК ==========
def main():
    app = Application.builder().token(TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("bj", bj))
    app.add_handler(CommandHandler("join", join))
    app.add_handler(CommandHandler("startgame", startgame))
    app.add_handler(CommandHandler("endgame", cmd_endgame))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # Планировщик сброса топа по МСК (воскресенье 23:59 MSK = 20:59 UTC)
    job_queue = app.job_queue
    if job_queue:
        # Устанавливаем московский часовой пояс
        msk_tz = pytz.timezone('Europe/Moscow')
        # Сброс каждое воскресенье в 23:59 по Москве
        job_queue.run_daily(
            weekly_reset, 
            time=datetime.time(hour=20, minute=59, second=0),  # 20:59 UTC = 23:59 MSK
            days=(6,),  # воскресенье в Python = 6
            context=context
        )

    print("✅ Бот запущен! Сброс топа по воскресеньям в 23:59 МСК")
    app.run_polling()

if __name__ == "__main__":
    main()