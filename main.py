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
    start = State()
    end = State()

# Utility functions
def make_button(text: str, callback: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback)

def chunk(lst, n):
    return [lst[i:i + n] for i in range(0, len(lst), n)]

# Mock busy slots
def get_busy():
    today = datetime.date.today()
    busy = []
    if today.day <= 20:
        d = today.replace(day=20)
        busy.append((datetime.datetime.combine(d, datetime.time(0)).isoformat() + 'Z',
                     datetime.datetime.combine(d, datetime.time(23, 59)).isoformat() + 'Z'))
    if today.day <= 21:
        d = today.replace(day=21)
        busy.append((datetime.datetime.combine(d, datetime.time(14)).isoformat() + 'Z',
                     datetime.datetime.combine(d, datetime.time(23, 59)).isoformat() + 'Z'))
    return busy

# /start and /rent handler
@dp.message(Command(commands=["start", "rent"]))
async def cmd_rent(msg: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        make_button('Зал 1', 'hall:1'),
        make_button('Зал 2', 'hall:2')
    ]])
    await msg.answer('Выберите зал:', reply_markup=kb)
    await state.set_state(RentForm.hall)

# Hall selection
@dp.callback_query(StateFilter(RentForm.hall), F.data.startswith('hall:'))
async def sel_hall(q: CallbackQuery, state: FSMContext):
    hall = q.data.split(':')[1]
    await state.update_data(hall=hall, busy=get_busy())
    today = datetime.date.today()
    await state.update_data(year=today.year, month=today.month)
    await show_calendar(q, state)
    await state.set_state(RentForm.month)

# Build and display calendar
async def show_calendar(q: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    year, month = data['year'], data['month']
    today = datetime.date.today()
    busy = data['busy']
    rows = []
    # Navigation row
    nav = []
    if (year, month) != (today.year, today.month):
        nav.append(make_button('◀️', 'prev'))
    nav.append(make_button(f'{calendar.month_name[month]} {year}', 'ignore'))
    nxt = today + datetime.timedelta(days=31)
    if (year, month) != (nxt.year, nxt.month):
        nav.append(make_button('▶️', 'next'))
    rows.append(nav)
    # Weekdays
    rows.append([make_button(d, 'ignore') for d in ['Mo','Tu','We','Th','Fr','Sa','Su']])
    # Days
    for week in calendar.monthcalendar(year, month):
        row = []
        for d in week:
            if d == 0:
                row.append(make_button(' ', 'ignore'))
            else:
                dt = datetime.date(year, month, d)
                free = any(
                    all(
                        not (datetime.datetime.fromisoformat(b[0].rstrip('Z')) < datetime.datetime.combine(dt, datetime.time(h+1))
                             and datetime.datetime.fromisoformat(b[1].rstrip('Z')) > datetime.datetime.combine(dt, datetime.time(h)))
                        for b in busy
                    )
                    for h in range(10, 22)
                ) and dt >= today
                txt = f'{d}' + ('' if free else ' ❌')
                cb = f'day:{dt.isoformat()}' if free else 'ignore'
                row.append(make_button(txt, cb))
        rows.append(row)
    # Back to hall
    rows.insert(0, [make_button('⬅️ Назад', 'back_hall')])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await q.message.edit_text('Выберите день:', reply_markup=kb)

# Calendar navigation
@dp.callback_query(StateFilter(RentForm.month), F.data == 'prev')
async def prev_month(q: CallbackQuery, state: FSMContext):
    today = datetime.date.today()
    await state.update_data(year=today.year, month=today.month)
    await show_calendar(q, state)

@dp.callback_query(StateFilter(RentForm.month), F.data == 'next')
async def next_month(q: CallbackQuery, state: FSMContext):
    today = datetime.date.today()
    nxt = today + datetime.timedelta(days=31)
    await state.update_data(year=nxt.year, month=nxt.month)
    await show_calendar(q, state)

# Back to hall
@dp.callback_query(StateFilter(RentForm.month), F.data == 'back_hall')
async def back_hall(q: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        make_button('Зал 1', 'hall:1'),
        make_button('Зал 2', 'hall:2')
    ]])
    await q.message.edit_text('Выберите зал:', reply_markup=kb)
    await state.set_state(RentForm.hall)

# Day -> Start time
@dp.callback_query(StateFilter(RentForm.month), F.data.startswith('day:'))
async def sel_day(q: CallbackQuery, state: FSMContext):
    day_str = q.data.split(':')[1]
    await state.update_data(day=day_str)
    data = await state.get_data()
    busy = data['busy']
    day = datetime.date.fromisoformat(day_str)
    buttons = []
    for h in range(10, 22):
        slot_s = datetime.datetime.combine(day, datetime.time(h))
        slot_e = slot_s + datetime.timedelta(hours=1)
        free = all(
            not (datetime.datetime.fromisoformat(b[0].rstrip('Z')) < slot_e
                 and datetime.datetime.fromisoformat(b[1].rstrip('Z')) > slot_s)
            for b in busy
        )
        txt = f'{h}' + ('' if free else ' ❌')
        cb = f'start:{h}' if free else 'ignore'
        buttons.append(make_button(txt, cb))
    rows = [[make_button('⬅️ Назад', 'back_cal')]] + chunk(buttons, 6)
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await q.message.edit_text('Выберите время начала:', reply_markup=kb)
    await state.set_state(RentForm.start)

# Back to calendar
@dp.callback_query(StateFilter(RentForm.start), F.data == 'back_cal')
async def back_cal(q: CallbackQuery, state: FSMContext):
    await show_calendar(q, state)
    await state.set_state(RentForm.month)

# Function to render start time selection (reuse for back navigation)
async def show_start(q: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    busy = data['busy']
    day = datetime.date.fromisoformat(data['day'])
    buttons = []
    for h in range(10, 22):
        slot_s = datetime.datetime.combine(day, datetime.time(h))
        slot_e = slot_s + datetime.timedelta(hours=1)
        free = all(
            not (datetime.datetime.fromisoformat(b[0].rstrip('Z')) < slot_e
                 and datetime.datetime.fromisoformat(b[1].rstrip('Z')) > slot_s)
            for b in busy
        )
        txt = f'{h}' + ('' if free else ' ❌')
        cb = f'start:{h}' if free else 'ignore'
        buttons.append(make_button(txt, cb))
    rows = [[make_button('⬅️ Назад', 'back_cal')]] + chunk(buttons, 6)
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await q.message.edit_text('Выберите время начала:', reply_markup=kb)
    await state.set_state(RentForm.start)

# Start -> End time
@dp.callback_query(StateFilter(RentForm.start), F.data.startswith('start:'))
async def sel_start(q: CallbackQuery, state: FSMContext):
    start_h = int(q.data.split(':')[1])
    await state.update_data(start=start_h)
    data = await state.get_data()
    busy = data['busy']
    day = datetime.date.fromisoformat(data['day'])
    buttons = []
    for h in range(start_h + 1, 23):
        slot_s = datetime.datetime.combine(day, datetime.time(h - 1))
        slot_e = slot_s + datetime.timedelta(hours=1)
        free = all(
            not (datetime.datetime.fromisoformat(b[0].rstrip('Z')) < slot_e
                 and datetime.datetime.fromisoformat(b[1].rstrip('Z')) > slot_s)
            for b in busy
        )
        txt = f'{h}' + ('' if free else ' ❌')
        cb = f'end:{h}' if free else 'ignore'
        buttons.append(make_button(txt, cb))
    rows = [[make_button('⬅️ Назад', 'back_start')]] + chunk(buttons, 6)
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await q.message.edit_text('Выберите время окончания:', reply_markup=kb)
    await state.set_state(RentForm.end)

# Back to start
@dp.callback_query(StateFilter(RentForm.end), F.data == 'back_start')
async def back_start(q: CallbackQuery, state: FSMContext):
    # Navigate back to start selection
    await show_start(q, state)

@dp.callback_query(StateFilter(RentForm.end), F.data == 'back_start')
async def back_start(q: CallbackQuery, state: FSMContext):
    # Re-render end options
    data = await state.get_data()
    busy = data['busy']
    day = datetime.date.fromisoformat(data['day'])
    start_h = data['start']
    buttons = []
    for h in range(start_h + 1, 23):
        slot_s = datetime.datetime.combine(day, datetime.time(h - 1))
        slot_e = slot_s + datetime.timedelta(hours=1)
        free = all(
            not (datetime.datetime.fromisoformat(b[0].rstrip('Z')) < slot_e
                 and datetime.datetime.fromisoformat(b[1].rstrip('Z')) > slot_s)
            for b in busy
        )
        txt = f'{h}' + ('' if free else ' ❌')
        cb = f'end:{h}' if free else 'ignore'
        buttons.append(make_button(txt, cb))
    rows = [[make_button('⬅️ Назад', 'back_start')]] + chunk(buttons, 6)
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    # Only edit if changed
    try:
        await q.message.edit_text('Выберите время окончания:', reply_markup=kb)
    except:
        pass
    await state.set_state(RentForm.end)

# End -> Finalize
@dp.callback_query(StateFilter(RentForm.end), F.data.startswith('end:'))
async def sel_end(q: CallbackQuery, state: FSMContext):
    end_h = int(q.data.split(':')[1])
    data = await state.get_data()
    text = f"[ТЕСТ] Забронировано зал {data['hall']} с {data['start']}:00 до {end_h}:00 на {datetime.date.fromisoformat(data['day']).strftime('%d.%m.%Y')}"
    await q.message.edit_text(text)
    await state.clear()

if __name__ == '__main__':
    asyncio.run(dp.start_polling(bot))
