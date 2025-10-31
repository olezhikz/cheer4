import logging
import json
import os
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# ==================== ВЕБ-СЕРВЕР ДЛЯ ПОДДЕРЖАНИЯ АКТИВНОСТИ ====================

app = Flask('')

@app.route('/')
def home():
    return "Бот активен!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# ==================== ЗАГРУЗКА ТОКЕНА ИЗ .ENV ====================

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')  # Ваш chat_id для отчетов

if not BOT_TOKEN:
    print("❌ Ошибка: Токен бота не найден. Проверьте файл .env")
    exit(1)

# ==================== КОНФИГУРАЦИЯ ====================

DATA_FILE = "clients_cheer4.json"
REMINDER_THRESHOLD = 1  # Напоминать когда осталось 1 занятие
REPORT_HOUR = 10        # Время отправки отчета (10:00)

# ==================== НАСТРОЙКА ЛОГИРОВАНИЯ ====================

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== РАБОТА С ДАННЫМИ ====================

def load_data():
    """Загружает данные о клиентах из JSON-файла."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                return convert_to_new_format(data)
            except json.JSONDecodeError:
                return {}
    return {}

def convert_to_new_format(data):
    """Конвертирует старый формат данных в новый с датами."""
    new_data = {}
    for client_name, client_data in data.items():
        if isinstance(client_data, dict):
            new_data[client_name] = client_data
        else:
            new_data[client_name] = {
                'sessions': client_data,
                'last_payment_date': datetime.now().isoformat(),
                'phone': '',
                'notes': ''
            }
    return new_data

def save_data(data):
    """Сохраняет данные о клиентах в JSON-файл."""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def add_sessions_to_client(client_name, sessions_to_add, phone="", notes=""):
    """Добавляет занятия абонемента клиенту."""
    data = load_data()
    if client_name in data:
        data[client_name]['sessions'] += sessions_to_add
        data[client_name]['last_payment_date'] = datetime.now().isoformat()
        if phone:
            data[client_name]['phone'] = phone
        if notes:
            data[client_name]['notes'] = notes
    else:
        data[client_name] = {
            'sessions': sessions_to_add,
            'last_payment_date': datetime.now().isoformat(),
            'phone': phone,
            'notes': notes
        }
    save_data(data)

def mark_attendance(client_name):
    """Отмечает посещение и возвращает остаток занятий."""
    data = load_data()
    if client_name in data and data[client_name]['sessions'] > 0:
        data[client_name]['sessions'] -= 1
        data[client_name]['last_attendance'] = datetime.now().isoformat()
        save_data(data)
        return data[client_name]['sessions']
    else:
        return None

def get_remaining_sessions(client_name):
    """Возвращает количество оставшихся занятий."""
    data = load_data()
    if client_name in data:
        return data[client_name]['sessions']
    return None

def get_client_info(client_name):
    """Возвращает полную информацию о клиенте."""
    data = load_data()
    return data.get(client_name)

def delete_client(client_name):
    """Удаляет клиента из базы данных."""
    data = load_data()
    if client_name in data:
        del data[client_name]
        save_data(data)
        return True
    return False

def ensure_data_file():
    """Создает файл данных если он не существует"""
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=4)
        print(f"✅ Файл {DATA_FILE} создан автоматически")

# ==================== СИСТЕМА НАПОМИНАНИЙ И ОТЧЕТОВ ====================

async def send_reminders(application):
    """Отправляет напоминания администратору о клиентах с 1 занятием."""
    data = load_data()
    reminders_sent = 0
    
    clients_with_one_session = []
    for client_name, client_data in data.items():
        sessions = client_data['sessions']
        if sessions == REMINDER_THRESHOLD:
            clients_with_one_session.append(client_name)
    
    if clients_with_one_session:
        message = "🔔 КЛИЕНТЫ С 1 ЗАНЯТИЕМ:\n\n"
        for client_name in clients_with_one_session:
            message += f"• {client_name}\n"
        
        message += f"\nВсего клиентов с 1 занятием: {len(clients_with_one_session)}"
        
        if ADMIN_CHAT_ID:
            try:
                await application.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=message
                )
                reminders_sent = len(clients_with_one_session)
                print(f"✅ Отправлены напоминания для {reminders_sent} клиентов")
            except Exception as e:
                print(f"❌ Ошибка отправки напоминаний: {e}")
    
    return reminders_sent

async def send_monthly_report(application):
    """Отправляет ежемесячный отчет администратору."""
    if not ADMIN_CHAT_ID:
        print("❌ ADMIN_CHAT_ID не указан, отчет не отправлен")
        return
        
    data = load_data()
    total_clients = len(data)
    total_sessions = sum(client_data['sessions'] for client_data in data.values())
    
    # Клиенты с 1 занятием
    clients_with_one_session = []
    for client_name, client_data in data.items():
        if client_data['sessions'] == REMINDER_THRESHOLD:
            clients_with_one_session.append(client_name)
    
    # Клиенты с 0 занятий
    clients_with_zero_sessions = []
    for client_name, client_data in data.items():
        if client_data['sessions'] == 0:
            clients_with_zero_sessions.append(client_name)
    
    # Новые клиенты за последний месяц
    month_ago = datetime.now() - timedelta(days=30)
    new_clients = []
    for client_name, client_data in data.items():
        payment_date = datetime.fromisoformat(client_data['last_payment_date'])
        if payment_date >= month_ago:
            new_clients.append(client_name)
    
    # Формируем отчет
    report = "📊 ЕЖЕМЕСЯЧНЫЙ ОТЧЕТ\n\n"
    report += f"👥 Всего клиентов: {total_clients}\n"
    report += f"🎫 Всего занятий в абонементах: {total_sessions}\n"
    report += f"🆕 Новых клиентов за месяц: {len(new_clients)}\n\n"
    
    if clients_with_one_session:
        report += "🔔 КЛИЕНТЫ С 1 ЗАНЯТИЕМ:\n"
        for client_name in clients_with_one_session:
            report += f"• {client_name}\n"
        report += f"\n"
    
    if clients_with_zero_sessions:
        report += "❌ КЛИЕНТЫ С 0 ЗАНЯТИЙ:\n"
        for client_name in clients_with_zero_sessions:
            report += f"• {client_name}\n"
        report += f"\n"
    
    if new_clients:
        report += f"🆕 НОВЫЕ КЛИЕНТЫ:\n" + "\n".join([f"• {name}" for name in new_clients])

    try:
        await application.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=report
        )
        print("✅ Ежемесячный отчет отправлен")
    except Exception as e:
        print(f"❌ Ошибка отправки отчета: {e}")

def is_monthly_report_day():
    """Проверяет, сегодня ли день для ежемесячного отчета (30-е или 28-е в феврале)."""
    now = datetime.now()
    day = now.day
    month = now.month
    
    # Февраль - 28-е
    if month == 2 and day == 28:
        return True
    # Все остальные месяцы - 30-е
    elif day == 30:
        return True
    
    return False

async def schedule_tasks(application):
    """Планирует задачи."""
    last_report_sent = None
    
    while True:
        now = datetime.now()
        
        # Проверяем, нужно ли отправить ежемесячный отчет
        if (is_monthly_report_day() and 
            now.hour == REPORT_HOUR and 
            now.minute == 0 and
            (last_report_sent is None or last_report_sent.date() != now.date())):
            
            await send_monthly_report(application)
            await send_reminders(application)
            last_report_sent = now
            print(f"✅ Ежемесячные задачи выполнены {now.strftime('%d.%m.%Y %H:%M')}")
        
        # Проверяем напоминания каждый день в 10:00
        elif (now.hour == REPORT_HOUR and 
              now.minute == 0 and
              (last_report_sent is None or last_report_sent.date() != now.date())):
            
            await send_reminders(application)
            last_report_sent = now
            print(f"✅ Ежедневные напоминания отправлены {now.strftime('%d.%m.%Y %H:%M')}")
        
        # Ждем 1 минуту до следующей проверки
        await asyncio.sleep(60)

# ==================== СОЗДАНИЕ КЛАВИАТУР ====================

def main_menu_keyboard():
    """Создает главное меню."""
    keyboard = [
        [InlineKeyboardButton("📋 Список клиентов", callback_data="list_clients")],
        [InlineKeyboardButton("➕ Добавить клиента", callback_data="add_client")],
        [InlineKeyboardButton("📊 Статистика", callback_data="statistics")],
        [InlineKeyboardButton("🔔 Тест напоминаний", callback_data="test_reminders")]
    ]
    return InlineKeyboardMarkup(keyboard)

def clients_list_keyboard():
    """Создает клавиатуру со списком клиентов."""
    data = load_data()
    keyboard = []
    
    for client_name in sorted(data.keys()):
        sessions = data[client_name]['sessions']
        button_text = f"{client_name} ({sessions} занятий)"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"client_{client_name}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

def client_actions_keyboard(client_name):
    """Создает клавиатуру действий для конкретного клиента."""
    keyboard = [
        [InlineKeyboardButton("✅ Отметить посещение", callback_data=f"attend_{client_name}")],
        [InlineKeyboardButton("➕ Добавить занятия", callback_data=f"add_sessions_{client_name}")],
        [InlineKeyboardButton("📋 Информация", callback_data=f"info_{client_name}")],
        [InlineKeyboardButton("📊 Проверить остаток", callback_data=f"check_{client_name}")],
        [InlineKeyboardButton("🗑️ Удалить клиента", callback_data=f"delete_ask_{client_name}")],
        [InlineKeyboardButton("🔙 К списку клиентов", callback_data="list_clients")]
    ]
    return InlineKeyboardMarkup(keyboard)

def delete_confirmation_keyboard(client_name):
    """Создает клавиатуру подтверждения удаления."""
    keyboard = [
        [InlineKeyboardButton("❌ Да, удалить", callback_data=f"delete_confirm_{client_name}")],
        [InlineKeyboardButton("✅ Нет, оставить", callback_data=f"client_{client_name}")]
    ]
    return InlineKeyboardMarkup(keyboard)

def back_to_main_menu_keyboard():
    """Клавиатура для возврата в главное меню."""
    keyboard = [
        [InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ==================== ОБРАБОТЧИКИ КОМАНД ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start."""
    print("✅ Команда /start получена!")
    await update.message.reply_text(
        "👯‍♀️ Учет занятий Чирлидинг (4+)\n\n"
        "Выберите действие:",
        reply_markup=main_menu_keyboard()
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки."""
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    print(f"✅ Нажата кнопка: {callback_data}")
    
    if callback_data == "main_menu":
        await query.edit_message_text(
            "👯‍♀️ Учет занятий Чирлидинг (4+)\n\nВыберите действие:",
            reply_markup=main_menu_keyboard()
        )
    
    elif callback_data == "list_clients":
        data = load_data()
        if not data:
            await query.edit_message_text(
                "📝 Список клиентов пуст.",
                reply_markup=main_menu_keyboard()
            )
        else:
            await query.edit_message_text(
                "👥 Выберите клиента:",
                reply_markup=clients_list_keyboard()
            )
    
    elif callback_data == "add_client":
        context.user_data['awaiting_client_name'] = True
        await query.edit_message_text(
            "👤 Добавление нового клиента\n\n"
            "Введите имя нового клиента:",
            reply_markup=back_to_main_menu_keyboard()
        )
    
    elif callback_data == "statistics":
        data = load_data()
        total_clients = len(data)
        total_sessions = sum(client_data['sessions'] for client_data in data.values())
        
        # Клиенты с 1 занятием
        clients_with_one_session = []
        for client_name, client_data in data.items():
            if client_data['sessions'] == REMINDER_THRESHOLD:
                clients_with_one_session.append(client_name)
        
        message = "📊 Статистика:\n\n"
        message += f"Всего клиентов: {total_clients}\n"
        message += f"Всего занятий в абонементах: {total_sessions}\n"
        
        if clients_with_one_session:
            message += f"\n🔔 Клиентов с 1 занятием: {len(clients_with_one_session)}\n"
            for client_name in clients_with_one_session[:5]:
                message += f"• {client_name}\n"
            if len(clients_with_one_session) > 5:
                message += f"... и еще {len(clients_with_one_session) - 5}\n"
        
        await query.edit_message_text(
            message,
            reply_markup=main_menu_keyboard()
        )
    
    elif callback_data == "test_reminders":
        sent_count = await send_reminders(context.application)
        if sent_count > 0:
            message = f"✅ Тестовые напоминания отправлены для {sent_count} клиентов"
        else:
            message = "✅ Нет клиентов с 1 занятием для напоминаний"
        
        await query.edit_message_text(
            message,
            reply_markup=main_menu_keyboard()
        )
    
    elif callback_data.startswith("client_"):
        client_name = callback_data[7:]
        remaining = get_remaining_sessions(client_name)
        
        await query.edit_message_text(
            f"👤 Клиент: {client_name}\n"
            f"📊 Осталось занятий: {remaining}\n\n"
            "Выберите действие:",
            reply_markup=client_actions_keyboard(client_name)
        )
    
    elif callback_data.startswith("info_"):
        client_name = callback_data[5:]
        client_info = get_client_info(client_name)
        
        if client_info:
            message = f"👤 Информация о клиенте:\n\n"
            message += f"Имя: {client_name}\n"
            message += f"Занятий: {client_info['sessions']}\n"
            
            if client_info['last_payment_date']:
                payment_date = datetime.fromisoformat(client_info['last_payment_date'])
                message += f"Последняя оплата: {payment_date.strftime('%d.%m.%Y')}\n"
            
            if client_info.get('last_attendance'):
                last_attendance = datetime.fromisoformat(client_info['last_attendance'])
                message += f"Последнее посещение: {last_attendance.strftime('%d.%m.%Y')}\n"
            
            if client_info['phone']:
                message += f"Телефон: {client_info['phone']}\n"
            
            if client_info['notes']:
                message += f"Заметки: {client_info['notes']}\n"
        else:
            message = f"❌ Клиент {client_name} не найден"
        
        await query.edit_message_text(
            message,
            reply_markup=client_actions_keyboard(client_name)
        )
    
    elif callback_data.startswith("attend_"):
        client_name = callback_data[7:]
        remaining = mark_attendance(client_name)
        
        if remaining is not None:
            message = f"✅ Посещение отмечено для {client_name}\n"
            message += f"📊 Осталось занятий: {remaining}"
            
            # Предупреждение если 1 занятие
            if remaining == REMINDER_THRESHOLD:
                message += f"\n\n🔔 Внимание! Осталось 1 занятие"
        else:
            message = f"❌ Не удалось отметить посещение для {client_name}\n"
            message += "Возможно, абонемент закончился или клиент не найден"
        
        await query.edit_message_text(
            message,
            reply_markup=client_actions_keyboard(client_name)
        )
    
    elif callback_data.startswith("check_"):
        client_name = callback_data[6:]
        remaining = get_remaining_sessions(client_name)
        
        if remaining is not None:
            message = f"👤 Клиент: {client_name}\n"
            message += f"📊 Осталось занятий: {remaining}"
            
            if remaining == REMINDER_THRESHOLD:
                message += f"\n\n🔔 Внимание! Осталось 1 занятие"
        else:
            message = f"❌ Клиент {client_name} не найден"
        
        await query.edit_message_text(
            message,
            reply_markup=client_actions_keyboard(client_name)
        )
    
    elif callback_data.startswith("add_sessions_"):
        client_name = callback_data[13:]
        context.user_data['add_sessions_client'] = client_name
        context.user_data['awaiting_sessions_count'] = True
        await query.edit_message_text(
            f"➕ Добавление занятий для {client_name}\n\n"
            "Введите количество занятий для добавления:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад", callback_data=f"client_{client_name}")]
            ])
        )
    
    elif callback_data.startswith("delete_ask_"):
        client_name = callback_data[11:]
        await query.edit_message_text(
            f"🗑️ Вы действительно хотите удалить клиента {client_name}?\n\n"
            "⚠️ Это действие нельзя отменить!",
            reply_markup=delete_confirmation_keyboard(client_name)
        )
    
    elif callback_data.startswith("delete_confirm_"):
        client_name = callback_data[15:]
        if delete_client(client_name):
            await query.edit_message_text(
                f"✅ Клиент {client_name} успешно удален!",
                reply_markup=main_menu_keyboard()
            )
        else:
            await query.edit_message_text(
                f"❌ Ошибка при удалении клиента {client_name}",
                reply_markup=main_menu_keyboard()
            )

# ==================== ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ ====================

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений."""
    text = update.message.text.strip()
    print(f"✅ Получено текстовое сообщение: {text}")
    
    if context.user_data.get('awaiting_client_name'):
        if not text:
            await update.message.reply_text("❌ Имя клиента не может быть пустым")
            return
        
        add_sessions_to_client(text, 0)
        context.user_data.pop('awaiting_client_name', None)
        
        await update.message.reply_text(
            f"✅ Клиент '{text}' успешно добавлен!\n"
            f"Теперь вы можете добавить занятия для него.",
            reply_markup=client_actions_keyboard(text)
        )
    
    elif context.user_data.get('awaiting_sessions_count'):
        try:
            sessions_to_add = int(text)
            if sessions_to_add <= 0:
                await update.message.reply_text("❌ Введите положительное число")
                return
                
            client_name = context.user_data.get('add_sessions_client')
            if client_name:
                add_sessions_to_client(client_name, sessions_to_add)
                remaining = get_remaining_sessions(client_name)
                
                context.user_data.pop('awaiting_sessions_count', None)
                context.user_data.pop('add_sessions_client', None)
                
                await update.message.reply_text(
                    f"✅ Добавлено {sessions_to_add} занятий для {client_name}\n"
                    f"📊 Теперь занятий: {remaining}",
                    reply_markup=client_actions_keyboard(client_name)
                )
        
        except ValueError:
            await update.message.reply_text("❌ Пожалуйста, введите число")
    
    else:
        await update.message.reply_text(
            "Используйте кнопки для работы с ботом",
            reply_markup=main_menu_keyboard()
        )

# ==================== ГЛАВНАЯ ФУНКЦИЯ ====================

def main():
    # Создаем Application и передаем ему токен бота
    application = Application.builder().token(BOT_TOKEN).build()

    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_text_message
    ))

    print("🤖 Бот Cheer9 запускается...")
    print(f"✅ Используется файл данных: {DATA_FILE}")
    print(f"✅ Напоминания для клиентов с: {REMINDER_THRESHOLD} занятием")
    print(f"✅ Ежемесячные отчеты: 30-го числа (28-го в феврале) в {REPORT_HOUR}:00")
    
    # Запускаем фоновые задачи
    loop = asyncio.get_event_loop()
    loop.create_task(schedule_tasks(application))
    
    application.run_polling()
    print("🛑 Бот остановлен")

# ==================== ЗАПУСК ПРИЛОЖЕНИЯ ====================

if __name__ == '__main__':
    ensure_data_file()  # Создаем файл данных если нужно
    keep_alive()        # Запускаем веб-сервер для поддержания активности
    main()              # Запускаем бота