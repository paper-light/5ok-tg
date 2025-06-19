import asyncio
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Message
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.filters.state import StateFilter
import datetime

# ---- Configuration ----
load_dotenv()
API_TOKEN = os.getenv("API_TOKEN")  # токен из переменных окружения

# ---- Bot and FSM setup ----
storage = MemoryStorage()
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=storage)

# Define states
class RentForm(StatesGroup):
    hall = State()
    day = State()
    start = State()
    end = State()

# Helper to fetch busy slots with mock: Friday 20th all day busy and Saturday 21st half-day busy
async def fetch_busy_intervals():
    today = datetime.date.today()
    busy = []
    # Full-day busy on the 20th
    try:
        bd1 = datetime.date(today.year, today.month, 20)
    except ValueError:
        bd1 = today
    busy.append((datetime.datetime.combine(bd1, datetime.time(0)).isoformat() + 'Z',
                 datetime.datetime.combine(bd1, datetime.time(23, 59)).isoformat() + 'Z'))
    # Half-day busy on the 21st (14:00-23:59)
    try:
        bd2 = datetime.date(today.year, today.month, 21)
    except ValueError:
        bd2 = today
    busy.append((datetime.datetime.combine(bd2, datetime.time(14)).isoformat() + 'Z',
                 datetime.datetime.combine(bd2, datetime.time(23, 59)).isoformat() + 'Z'))
    return busy

# Utility: split list into chunks of size n
def chunk_list(lst, n):
    return [lst[i:i + n] for i in range(0, len(lst), n)]

# Start command: choose hall
@dp.message(Command(commands=["start", "rent"]))
async def cmd_rent(message: Message, state: FSMContext):
    keyboard = [[
        InlineKeyboardButton(text='Зал 1', callback_data='hall:1'),
        InlineKeyboardButton(text='Зал 2', callback_data='hall:2')
    ]]
    kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
    await message.answer('Выберите зал для аренды:', reply_markup=kb)
    await state.set_state(RentForm.hall)

# Hall chosen: update message with days
@dp.callback_query(StateFilter(RentForm.hall), F.data.startswith('hall:'))
async def process_hall(query: CallbackQuery, state: FSMContext):
    await state.update_data(hall=query.data.split(':')[1])
    busy = await fetch_busy_intervals()
    await state.update_data(busy=busy)
    today = datetime.date.today()

    keyboard = []
    for week in range(5):
        row = []
        for d in range(7):
            day = today + datetime.timedelta(days=week*7+d)
            if day > today + datetime.timedelta(days=29):
                break
            free = any(
                not (datetime.datetime.fromisoformat(b[0].rstrip('Z')) < datetime.datetime.combine(day, datetime.time(h+1))
                     and datetime.datetime.fromisoformat(b[1].rstrip('Z')) > datetime.datetime.combine(day, datetime.time(h)))
                for h in range(10,22) for b in busy)
            text = day.strftime('%a %d') + ('' if free else ' ❌')
            cb = f'day:{day.isoformat()}' if free else f'none_day:{day.isoformat()}'
            row.append(InlineKeyboardButton(text=text, callback_data=cb))
        keyboard.append(row)

    kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
    # Edit previous message instead of sending new
    await query.message.edit_text('Выберите день:', reply_markup=kb)
    await state.set_state(RentForm.day)

# Day chosen: update message with start hours
@dp.callback_query(StateFilter(RentForm.day), F.data.startswith('day:'))
async def process_day(query: CallbackQuery, state: FSMContext):
    day_str = query.data.split(':')[1]
    await state.update_data(day=day_str)
    busy = (await state.get_data())['busy']
    day = datetime.date.fromisoformat(day_str)

    buttons = []
    for h in range(10, 22):
        slot_s = datetime.datetime.combine(day, datetime.time(h))
        slot_e = slot_s + datetime.timedelta(hours=1)
        free = all(
            not (datetime.datetime.fromisoformat(b[0].rstrip('Z')) < slot_e and
                 datetime.datetime.fromisoformat(b[1].rstrip('Z')) > slot_s)
            for b in busy)
        text = f'{h}' + ('' if free else ' ❌')
        cb = f'start:{h}' if free else f'none_hour:{h}'
        buttons.append(InlineKeyboardButton(text=text, callback_data=cb))
    rows = chunk_list(buttons, 6)
    kb = InlineKeyboardMarkup(inline_keyboard=rows)

    await query.message.edit_text('Выберите время начала:', reply_markup=kb)
    await state.set_state(RentForm.start)

# Start time chosen: update message with end hours
@dp.callback_query(StateFilter(RentForm.start), F.data.startswith('start:'))
async def process_start(query: CallbackQuery, state: FSMContext):
    start_h = int(query.data.split(':')[1])
    await state.update_data(start=start_h)
    data = await state.get_data()
    busy = data['busy']
    day = datetime.date.fromisoformat(data['day'])

    buttons = []
    for h in range(start_h+1, 23):
        slot_s = datetime.datetime.combine(day, datetime.time(h-1))
        slot_e = slot_s + datetime.timedelta(hours=1)
        free = all(
            not (datetime.datetime.fromisoformat(b[0].rstrip('Z')) < slot_e and
                 datetime.datetime.fromisoformat(b[1].rstrip('Z')) > slot_s)
            for b in busy)
        text = f'{h}' + ('' if free else ' ❌')
        cb = f'end:{h}' if free else f'none_hour:{h}'
        buttons.append(InlineKeyboardButton(text=text, callback_data=cb))
    rows = chunk_list(buttons, 6)
    kb = InlineKeyboardMarkup(inline_keyboard=rows)

    await query.message.edit_text('Выберите время окончания:', reply_markup=kb)
    await state.set_state(RentForm.end)

# End time chosen: send result and clear or replace
@dp.callback_query(StateFilter(RentForm.end), F.data.startswith('end:'))
async def process_end(query: CallbackQuery, state: FSMContext):
    end_h = int(query.data.split(':')[1])
    data = await state.get_data()
    text = (f'[ТЕСТ] Забронировано: зал {data["hall"]} с {data["start"]}:00 ' 
            f'до {end_h}:00 на {datetime.date.fromisoformat(data["day"]).strftime("%d.%m.%Y")}.' )
    await query.message.edit_text(text)
    await state.clear()

# Handlers for none_day and none_hour
@dp.callback_query(F.data.startswith('none_day:'), StateFilter(RentForm.hall))
async def no_day(query: CallbackQuery):
    date = query.data.split(':')[1]
    await query.answer(f'Нет свободных часов на {datetime.date.fromisoformat(date).strftime("%d.%m.%Y")}')

@dp.callback_query(F.data.startswith('none_hour:'), StateFilter(RentForm.start))
async def no_hour(query: CallbackQuery):
    await query.answer('Этот час занят')

# Start polling
if __name__ == '__main__':
    asyncio.run(dp.start_polling(bot))
