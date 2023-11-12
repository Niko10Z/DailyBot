import telebot
import config
import const
import re
import sqlalchemy
from sqlalchemy.orm import declarative_base, sessionmaker
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Tuple

BOT_STATE = const.BOT_MODES.listen
task_dict = {}

bot = telebot.TeleBot(token=config.TOKEN)

engine = sqlalchemy.create_engine("sqlite:///bot_mem.sqlite", echo=True)
Base = declarative_base()
Session = sessionmaker(bind=engine)


class DailyRoutine(Base):
    __tablename__ = "daily_routine"

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    user_id = sqlalchemy.Column(sqlalchemy.Integer)
    task_title = sqlalchemy.Column(sqlalchemy.String)
    task_date = sqlalchemy.Column(sqlalchemy.Date)
    task_text = sqlalchemy.Column(sqlalchemy.String)
    rank = sqlalchemy.Column(sqlalchemy.SmallInteger, default=0)
    is_done = sqlalchemy.Column(sqlalchemy.Boolean, default=False)


Base.metadata.create_all(engine)


def get_period(date_str: str) -> Tuple[date, date]:
    now = datetime.today().date()
    period_words = {
        'day': lambda: (now, now),
        'week': lambda: (now - timedelta(days=now.weekday()), now + timedelta(days=7 - now.weekday() - 1)),
        'month': lambda: (date(now.year, now.month, 1), date(now.year, now.month, monthrange(now.year, now.month)[1])),
        'year': lambda: (date(now.year, 1, 1), date(now.year, 12, 31)),
    }
    if date_str in period_words:
        return period_words[date_str]()
    else:
        raise ValueError('Unknown period name')


def convert_date(date_str: str) -> date:
    day_words = {
        'now': lambda : datetime.today().date(),
        'today': lambda : datetime.today().date(),
        'сегодня': lambda: datetime.today().date(),
        'tomorrow': lambda: datetime.today().date() + timedelta(days=1),
        'завтра': lambda: datetime.today().date() + timedelta(days=1),
        'послезавтра': lambda: datetime.today().date() + timedelta(days=2),
    }
    local_date_str = date_str.lower()
    if local_date_str in day_words:
        return day_words[local_date_str]()
    elif re.match(r'^[0123]{0,1}\d[\.\-/\\\_][01]{0,1}\d[\.\-/\\\_]\d{1,4}$', local_date_str):
        local_date_str = re.sub(r'[\-/\\]', '.', local_date_str)
        try:
            return datetime.strptime(local_date_str, '%d.%m.%Y').date()
        except ValueError:
            raise ValueError('Wrong date string format')
    else:
        raise ValueError('Unconvertable date string')


def add_task(task_title: str, task_date: date, task_text: str, user_id: int) -> None:
    with Session() as session:
        session.add(DailyRoutine(user_id=user_id, task_title=task_title, task_date=task_date, task_text=task_text))
        session.commit()


def show_routine(user_id: int = None, on_date: date = None, till_date: date = None) -> str:
    if not user_id:
        raise ValueError('User ID must be int')
    with Session() as session:
        if on_date:
            if till_date:
                query_set = session.query(DailyRoutine).filter(DailyRoutine.user_id == user_id,
                                                               DailyRoutine.task_date >= on_date,
                                                               DailyRoutine.task_date <= till_date).order_by(DailyRoutine.task_date,
                                                                                                             DailyRoutine.rank,
                                                                                                             DailyRoutine.id)
            else:
                query_set = session.query(DailyRoutine).filter_by(user_id=user_id,
                                                                  task_date=on_date).order_by(DailyRoutine.rank,
                                                                                              DailyRoutine.id)
        else:
            query_set = session.query(DailyRoutine).filter_by(user_id=user_id).order_by(DailyRoutine.task_date,
                                                                                        DailyRoutine.rank,
                                                                                        DailyRoutine.id)
        tasks_text = ''
        tmp_date = None
        for elem in query_set:
            if elem.task_date != tmp_date:
                tmp_date = elem.task_date
                tasks_text += f'\n{elem.task_date.strftime("%d-%m-%Y")}\n'
            tasks_text += f'\t-{elem.task_title}({elem.task_text})\n'
    return tasks_text


@bot.message_handler(commands=['start', 'help'])
def command_help(message: telebot.types.Message) -> None:
    HELP = """\n  
    /help - напечатать справку по программе
    /add - добавить задачу в список
    /show - напечатать все добавленные задачи
         --[period(day,week,month,year) | date(today,tomorrow,dd-mm-yyyy)]
         --[date_till(dd-mm-2023)]
    /done - отметить выполнение задачи
    \n
    """
    # Шлёт сообщение
    bot.send_message(message.chat.id, HELP)
    # Отвечает на сообщение
    # bot.reply_to(message, HELP)


# @bot.message_handler(commands=['add'])
# def command_add(message):
#     command, task_title, task_date, task_text = message.text.split(' ', maxsplit=3)
#     add_task(task_title, convert_date(task_date), task_text, message.from_user.id)
#     bot.send_message(message.chat.id, 'Task added')
@bot.message_handler(commands=['add'])
def command_add(message):
    global BOT_STATE
    BOT_STATE = const.BOT_MODES.add_task
    bot.send_message(message.chat.id, 'Enter title of task')


@bot.message_handler(commands=['show'])
def command_show(message):
    command, *args = message.text.split(' ', maxsplit=2)
    try:
        if args[0] in ['day', 'week', 'month', 'year']:
            on_date, till_date = get_period(args[0])
        else:
            on_date = convert_date(args[0])
            if len(args) > 1:
                till_date = convert_date(args[1])
            else:
                till_date = None
    except IndexError:
        on_date = None
        till_date = None
    bot.send_message(message.chat.id, show_routine(message.from_user.id, on_date, till_date))


@bot.message_handler(content_types=['text'])
def mess_listener(message):
    global BOT_STATE
    if BOT_STATE == const.BOT_MODES.add_task:
        if 'title' not in task_dict:
            task_dict['title'] = message.text
            bot.send_message(message.chat.id, 'Enter date (dd-mm-yyyy) of task')
        elif 'date' not in task_dict:
            task_dict['date'] = convert_date(message.text)
            bot.send_message(message.chat.id, 'Enter text of task')
        else:
            task_dict['text'] = message.text
            add_task(task_dict['title'], task_dict['date'], task_dict['text'], message.from_user.id)
            task_dict.clear()
            BOT_STATE = const.BOT_MODES.listen
            bot.send_message(message.chat.id, 'Task added')
    else:
        bot.send_message(message.chat.id, "Can't understand. Use /help to see command pool")


bot.infinity_polling()
