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
import calendar

# ---- Configuration ----
load_dotenv()
API_TOKEN = os.getenv("API_TOKEN")

# ---- Bot and FSM setup ----
storage = MemoryStorage()
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=storage)

# Define states
class RentForm(StatesGroup):
    hall = State()
    month = State()
    day = State()
    start = State()
    end = State()

# Helper: mock busy slots
async def fetch_busy_intervals():
    today = datetime.date.today()
    busy = []
    # Full-day busy on the 20th
    if today.day <= 20:
        bd1 = today.replace(day=20)
        busy.append((datetime.datetime.combine(bd1, datetime.time(0)).isoformat() + 'Z',
                     datetime.datetime.combine(bd1, datetime.time(23, 59)).isoformat() + 'Z'))
    # Half-day busy on the 21st
    if today.day <= 21:
        bd2 = today.replace(day=21)
        busy.append((datetime.datetime.combine(bd2, datetime.time(14)).isoformat() + 'Z',
                     datetime.datetime.combine(bd2, datetime.time(23, 59)).isoformat() + 'Z'))
    return busy

# Utility: split list into chunks of size n
def chunk_list(lst, n):
    return [lst[i:i + n] for i in range(0, len(lst), n)]

# Build inline keyboard for a given month
def build_month_keyboard(year, month, busy, today):
    # Determine allowed navigation
    prev_allowed = (year, month) != (today.year, today.month)
    next_allowed = (year, month) != ((today + datetime.timedelta(days=31)).year,
                                       (today + datetime.timedelta(days=31)).month)
    # Header
    buttons = []
    if prev_allowed:
        buttons.append(InlineKeyboardButton(text='◀️', callback_data='prev_month'))
    buttons.append(InlineKeyboardButton(text=f'{calendar.month_name[month]} {year}', callback_data='ignore'))
    if next_allowed:
        buttons.append(InlineKeyboardButton(text='▶️', callback_data='next_month'))
    keyboard = [buttons]
    # Weekday labels
    wkdays = ['Mo','Tu','We','Th','Fr','Sa','Su']
    keyboard.append([InlineKeyboardButton(text=w, callback_data='ignore') for w in wkdays])
    # Days
    for week in calendar.monthcalendar(year, month):
        row = []
        for d in week:
            if d == 0:
                row.append(InlineKeyboardButton(text=' ', callback_data='ignore'))
            else:
                day_date = datetime.date(year, month, d)
                # Determine if there are free slots on this day
                free_slots = False
                for h in range(10, 22):
                    slot_start = datetime.datetime.combine(day_date, datetime.time(h))
                    slot_end = slot_start + datetime.timedelta(hours=1)
                    if all(
                        not (datetime.datetime.fromisoformat(b[0].rstrip('Z')) < slot_end and
                             datetime.datetime.fromisoformat(b[1].rstrip('Z')) > slot_start)
                        for b in busy
                    ):
                        free_slots = True
                        break
                free = free_slots and day_date >= today
                text = f'{d}' + ('' if free else ' ❌')
                cb = f'day:{day_date.isoformat()}' if free else 'ignore'
                row.append(InlineKeyboardButton(text=text, callback_data=cb))
        keyboard.append(row)
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# Start command: choose hall
@dp.message(Command(commands=["start", "rent"]))
async def cmd_rent(message: Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='Зал 1', callback_data='hall:1'),
        InlineKeyboardButton(text='Зал 2', callback_data='hall:2')
    ]])
    await message.answer('Выберите зал для аренды:', reply_markup=kb)
    await state.set_state(RentForm.hall)

# Hall chosen: show month view (current month)
@dp.callback_query(StateFilter(RentForm.hall), F.data.startswith('hall:'))
async def process_hall(query: CallbackQuery, state: FSMContext):
    hall = query.data.split(':')[1]
    await state.update_data(hall=hall)
    today = datetime.date.today()
    await state.update_data(year=today.year, month=today.month)
    busy = await fetch_busy_intervals()
    await state.update_data(busy=busy)
    await state.update_data(busy=busy)
    kb = build_month_keyboard(today.year, today.month, busy, today)
    await query.message.edit_text('Выберите день:', reply_markup=kb)
    await state.set_state(RentForm.month)

# Month navigation
@dp.callback_query(StateFilter(RentForm.month), (F.data == 'prev_month') | (F.data == 'next_month'))
async def navigate_month(query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    year, month = data['year'], data['month']
    today = datetime.date.today()
    if query.data == 'prev_month':
        year, month = today.year, today.month
    else:
        nxt = today + datetime.timedelta(days=31)
        year, month = nxt.year, nxt.month
    await state.update_data(year=year, month=month)
    busy = await fetch_busy_intervals()
    kb = build_month_keyboard(year, month, busy, today)
    await query.message.edit_text('Выберите день:', reply_markup=kb)

# Day chosen: show start hours
@dp.callback_query(StateFilter(RentForm.month), F.data.startswith('day:'))
async def process_day(query: CallbackQuery, state: FSMContext):
    day_str = query.data.split(':')[1]
    await state.update_data(day=day_str)
    data = await state.get_data()
    busy = data['busy']
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
        cb = f'start:{h}' if free else 'ignore'
        buttons.append(InlineKeyboardButton(text=text, callback_data=cb))
    kb = InlineKeyboardMarkup(inline_keyboard=chunk_list(buttons, 6))
    await query.message.edit_text('Выберите время начала:', reply_markup=kb)
    await state.set_state(RentForm.start)

# Start time chosen: show end hours
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
        cb = f'end:{h}' if free else 'ignore'
        buttons.append(InlineKeyboardButton(text=text, callback_data=cb))
    kb = InlineKeyboardMarkup(inline_keyboard=chunk_list(buttons, 6))
    await query.message.edit_text('Выберите время окончания:', reply_markup=kb)
    await state.set_state(RentForm.end)

# End time chosen: finalize
@dp.callback_query(StateFilter(RentForm.end), F.data.startswith('end:'))
async def process_end(query: CallbackQuery, state: FSMContext):
    end_h = int(query.data.split(':')[1])
    data = await state.get_data()
    text = (f'[ТЕСТ] Забронировано: зал {data["hall"]} с {data["start"]}:00 '
            f'до {end_h}:00 на {datetime.date.fromisoformat(data["day"]).strftime("%d.%m.%Y")}.' )
    await query.message.edit_text(text)
    await state.clear()

# Start polling
if __name__ == '__main__':
    asyncio.run(dp.start_polling(bot))
