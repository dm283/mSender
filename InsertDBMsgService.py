import sys, os, configparser, re, datetime, json, asyncio, email, tkinter as tk
import requests, aioodbc
from aiosmtplib import SMTP
from aioimaplib import aioimaplib
from cryptography.fernet import Fernet
from tkinter import ttk

# загрузка конфигурации
CONFIG_FILE = 'config.ini'
config = configparser.ConfigParser()
config.read(CONFIG_FILE, encoding='utf-8')

# загрузка ключа шифрования
with open('rec-k.txt') as f:
    rkey = f.read().encode('utf-8')
refKey = Fernet(rkey)

# расшифровка хэшированных значений конфигурации
hashed_user_credentials_password = config['user_credentials']['password'].split('\t#')[0]
user_credentials_password = (refKey.decrypt(hashed_user_credentials_password).decode('utf-8'))
hashed_common_bot_token = config['telegram_bot']['bot_token'].split('\t#')[0]
common_bot_token = (refKey.decrypt(hashed_common_bot_token).decode('utf-8'))
hashed_email_server_password = config['email']['server_password'].split('\t#')[0]
email_server_password = (refKey.decrypt(hashed_email_server_password).decode('utf-8'))

CHECK_DB_PERIOD = int(config['common']['check_db_period'].split('\t#')[0])  # период проверки новых записей в базе данных

USER_NAME = config['user_credentials']['name'].split('\t#')[0]
USER_PASSWORD = user_credentials_password

ADMIN_EMAIL = config['admin_credentials']['email'].split('\t#')[0]  # почта админа

BOT_NAME = config['telegram_bot']['bot_name'].split('\t#')[0]
BOT_TOKEN = common_bot_token
TELEGRAM_DB = config['telegram_bot']['db'].split('\t#')[0]  # база данных mssql/posgres
TELEGRAM_DB_TABLE_MESSAGES = config['telegram_bot']['db_table_messages'].split('\t#')[0]  # db.schema.table
TELEGRAM_DB_TABLE_CHATS = config['telegram_bot']['db_table_chats'].split('\t#')[0]  # db.schema.table  таблица с telegram-чатами
TELEGRAM_DB_CONNECTION_STRING = config['telegram_bot']['db_connection_string'].split('\t#')[0]  # odbc driver system dsn name
ADMIN_BOT_CHAT_ID = str()  # объявление глобальной константы, которая записывается в функции load_telegram_chats_from_db
MODE_EMAIL, MODE_TELEGRAM = bool(), bool()

SENDER_EMAIL, EMAIL_SERVER_PASSWORD = config['email']['sender_email'].split('\t#')[0], email_server_password
SMTP_HOST, SMTP_PORT = config['email']['smtp_host'].split('\t#')[0], config['email']['smtp_port'].split('\t#')[0]
TEST_MESSAGE = f"""To: {ADMIN_EMAIL}\nFrom: {SENDER_EMAIL}
Subject: Mailsender - тестовое сообщение\n
Это тестовое сообщение отправленное сервисом Mailsender.""".encode('utf8')
UNDELIVERED_MESSAGE = f"""To: {ADMIN_EMAIL}\nFrom: {SENDER_EMAIL}
Subject: Mailsender - недоставленное сообщение\n
Это сообщение отправленно сервисом Mailsender.\n""".encode('utf8')
IMAP_HOST, IMAP_PORT = config['email']['imap_host'].split('\t#')[0], config['email']['imap_port'].split('\t#')[0]
EMAIL_DB = config['email']['db'].split('\t#')[0]
EMAIL_DB_CONNECTION_STRING = config['email']['db_connection_string'].split('\t#')[0]
EMAIL_DB_TABLE_EMAILS = config['email']['db_table_emails'].split('\t#')[0]

REGEX_EMAIL_VALID = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b' # шаблон для валидации e-mail адреса

ERROR_EMAIL_LIST = []  # список несуществующих адресов
error_email_list_path = 'error-emails-list.log'
if os.path.exists(error_email_list_path):
    with open(error_email_list_path, 'r') as f:
        for l in f.readlines():
            ERROR_EMAIL_LIST.append(l.split('\t')[-1].strip())

ROBOT_START = False
ROBOT_STOP = False
APP_EXIT = False
SIGN_IN_FLAG = False
THEME_COLOR = 'Gainsboro'
TK_FONT = 'Segoe UI'
LBL_COLOR = THEME_COLOR
LBL_ROBOT_MSG_COLOR = 'LightGray'
ENT_COLOR = 'White'
BTN_SIGN_IN_COLOR = 'Green'
BTN_START_COLOR = 'SeaGreen'
BTN_STOP_COLOR = 'SlateGray'
BTN_EXIT_COLOR = 'OrangeRed'
BTN_TEXT_COLOR = 'White'
BTN_EXIT_TEXT_COLOR = 'Black'
BTN_FONT = (TK_FONT, 12, 'bold')
RUNNER_COLOR = 'DodgerBlue'


# === INTERFACE FUNCTIONS ===
async def btn_sign_click():
    # кнопка sign-in
    global SIGN_IN_FLAG
    user = ent_user.get()
    password = ent_password.get()
    if user == USER_NAME and password == USER_PASSWORD:
        lbl_msg_sign["text"] = ''
        SIGN_IN_FLAG = True
        root.destroy()
    else:
        lbl_msg_sign["text"] = 'Incorrect username or password'


async def show_password_signin():
    # показывает/скрывает пароль в окне входа
    ent_password['show'] = '' if(cbt_sign_show_pwd_v1.get() == 1) else '*'


async def btn_email_insert_db_click():
    # Кнопка записи в бд email-сообщения
    adrto = ent['email']['to'].get().strip()
    subj = ent['email']['subj'].get().strip()
    textemail = ent['email']['text'].get(1.0, "end-1c").strip()
    
    if adrto == '' or subj == '' or textemail == '':
        lbl_msg_send['email']['text'] = 'Заполните все поля e-mail сообщения.'
        return 1

    # Проверка корректности e-mail адресов
    addrs = adrto.split(';')
    for a in addrs:
        if not (re.fullmatch(REGEX_EMAIL_VALID, a)):
            lbl_msg_send['email']['text'] = f'Некорректный e-mail адрес {a}.'
            return 1

    try:
        cnxn = await aioodbc.connect(dsn=EMAIL_DB_CONNECTION_STRING, loop=loop_msg_service)
        cursor = await cnxn.cursor()
    except:
        lbl_msg_send['email']['text'] = f"Подключение к базе данных {EMAIL_DB} -  ошибка."
        return 1

    lbl_msg_send['email']['text'] = f'Запись в базу данных .....'
    await asyncio.sleep(0.5)

    
    datep = str(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    query = f""" insert into {EMAIL_DB_TABLE_EMAILS} (subj, textemail, adrto, datep) values
                ('{subj}', '{textemail}', '{adrto}', '{datep}') """
    try:
        await cursor.execute(query)
        await cnxn.commit()
        lbl_msg_send['email']['text'] = f'Записано в базу данных.'
    except:
        lbl_msg_send['email']['text'] = f"Ошибка записи в базу данных {EMAIL_DB} -  ошибка."
        return 1

    await cursor.close()
    await cnxn.close()


async def btn_telegram_insert_db_click():
    # Кнопка записи в бд telegram-сообщения
    msg_text = ent['telegram']['text'].get(1.0, "end-1c").strip()
    adrto = ent['telegram']['to'].get().strip()

    if adrto == '' or msg_text == '':
        lbl_msg_send['telegram']['text'] = 'Заполните все поля telegram сообщения'
        return 1

    try:
        cnxn = await aioodbc.connect(dsn=TELEGRAM_DB_CONNECTION_STRING, loop=loop_msg_service)
        cursor = await cnxn.cursor()
    except:
        lbl_msg_send['telegram']['text'] = f"Подключение к базе данных {TELEGRAM_DB} -  ошибка."
        return 1

    lbl_msg_send['telegram']['text'] = f'Запись в базу данных .....'
    await asyncio.sleep(0.5)

    datep = str(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    query = f""" insert into {TELEGRAM_DB_TABLE_MESSAGES} (msg_text, adrto, datep) values
                ('{msg_text}', '{adrto}', '{datep}') """
    try:
        await cursor.execute(query)
        await cnxn.commit()
        lbl_msg_send['telegram']['text'] = f'Записано в базу данных.'
    except:
        lbl_msg_send['telegram']['text'] = f"Ошибка записи в базу данных {TELEGRAM_DB} -  ошибка."
        return 1

    await cursor.close()
    await cnxn.close()


async def btn_slice_msg_click(msg_type, move_type):
    # Кнопки перемещения по отправленным сообщениям
    print(msg_type, move_type)


async def show_signin():
    # рисует окно входа
    frm.pack()
    lbl_user.place(x=95, y=43)
    ent_user.place(x=95, y=86)
    lbl_password.place(x=95, y=110)
    ent_password.place(x=95, y=153)
    cbt_sign_show_pwd.place(x=95, y=180)
    btn_sign.place(x=95, y=220)
    lbl_msg_sign.place(x=95, y=270)

    while not SIGN_IN_FLAG:
        root.update()
        await asyncio.sleep(.1)


async def show_send_msg():
    # рисует окно записи сообщений
    notebook.pack(padx=10, pady=10, fill='both', expand=True)

    # Вкладка email-сообщений ============================
    notebook.add(frm['email'], text='E-mail')

    frm_msg_form['email'].pack(padx=5, pady=(5, 0), fill='both', expand=True)
    lbl['email']['description'].grid(row=0, columnspan=2, sticky='w', padx=5, pady=5)
    lbl['email']['to'].grid(row=1, column=0, sticky='w', padx=5, pady=5)
    ent['email']['to'].grid(row=1, column=1, sticky='w', padx=5, pady=5)
    lbl['email']['subj'].grid(row=2, column=0, sticky='w', padx=5, pady=5)
    ent['email']['subj'].grid(row=2, column=1, sticky='w', padx=5, pady=5)
    ent['email']['text'].grid(row=3, columnspan=2, sticky='w', padx=5, pady=5)

    frm_sending['email'].pack(padx=5, pady=(1, 5), fill='both', expand=True)
    btn_send['email'].grid(row=0, column=0, padx=5, pady=5)    
    lbl_msg_send['email'].grid(row=0, column=1, padx=5, pady=5)

    #frm_sent_msg_header
    #frm_sent_messages

    # frm_footer.pack(padx=10, pady=(0, 10), fill='both', expand=True)  
    # btn_save_config.grid(row = 0, column = 0)
    # lbl_config_msg.grid(row = 0, column = 1, padx = 10)

    # Вкладка telegram-сообщений ============================
    notebook.add(frm['telegram'], text='Telegram')

    frm_msg_form['telegram'].pack(padx=5, pady=(5, 0), fill='both', expand=True)
    lbl['telegram']['description'].grid(row=0, columnspan=2, sticky='w', padx=5, pady=5)
    lbl['telegram']['entity'].grid(row=1, column=0, sticky='w', padx=5, pady=5)
    ent['telegram']['entity'].grid(row=1, column=1, sticky='w', padx=5, pady=5)
    lbl['telegram']['to'].grid(row=2, column=0, sticky='w', padx=5, pady=5)
    ent['telegram']['to'].grid(row=2, column=1, sticky='w', padx=5, pady=5)
    ent['telegram']['text'].grid(row=3, columnspan=2, sticky='w', padx=5, pady=5)

    frm_sending['telegram'].pack(padx=5, pady=(1, 5), fill='both', expand=True)
    btn_send['telegram'].grid(row=0, column=0, padx=5, pady=5)    
    lbl_msg_send['telegram'].grid(row=0, column=1, padx=5, pady=5)

    while True:
        root_send_msg.update()
        await asyncio.sleep(.1)

# ============== window sign in
root = tk.Tk()
root.resizable(0, 0)  # делает неактивной кнопку Развернуть
root.title('InsertDBMsgService')
frm = tk.Frame(bg=THEME_COLOR, width=400, height=350)
#lbl_sign = tk.Label(master=frm, text='Sign in to ', bg=LBL_COLOR, font=(TK_FONT, 15), width=21, height=2)
lbl_user = tk.Label(master=frm, text='Username', bg=LBL_COLOR, font=(TK_FONT, 12), anchor='w', width=25, height=2)
ent_user = tk.Entry(master=frm, bg=ENT_COLOR, font=(TK_FONT, 12), width=25, )
lbl_password = tk.Label(master=frm, text='Password', bg=LBL_COLOR, font=(TK_FONT, 12), anchor='w', width=25, height=2)
ent_password = tk.Entry(master=frm, show='*', bg=ENT_COLOR, font=(TK_FONT, 12), width=25, )

cbt_sign_show_pwd_v1 = tk.IntVar(value = 0)
cbt_sign_show_pwd = tk.Checkbutton(frm, bg=THEME_COLOR, text='Show password', variable=cbt_sign_show_pwd_v1, onvalue=1, offvalue=0, 
                                    command=lambda: loop.create_task(show_password_signin()))

btn_sign = tk.Button(master=frm, bg=BTN_SIGN_IN_COLOR, fg='White', text='Sign in', font=(TK_FONT, 12, "bold"), 
                    width=22, height=1, command=lambda: loop.create_task(btn_sign_click()))
lbl_msg_sign = tk.Label(master=frm, bg=LBL_COLOR, fg='PaleVioletRed', font=(TK_FONT, 12), width=25, height=2)


development_mode = True     # True - для разработки окна робота переход сразу на него без sign in
if development_mode:    # для разработки окна робота переход сразу на него без sign in
    SIGN_IN_FLAG = True
else:
    loop = asyncio.get_event_loop()
    loop.run_until_complete(show_signin())

# выход из приложения если принудительно закрыто окно логина
# c asyncio не работает, надо выяснять!
if not SIGN_IN_FLAG:
    print('SIGN IN FALSE')
    #print('loop = ', loop)
    sys.exit()

# ============== window send_message
root_send_msg = tk.Tk()
root_send_msg.resizable(0, 0)  # делает неактивной кнопку Развернуть
root_send_msg.title('InsertDBMsgService')
notebook = ttk.Notebook(root_send_msg)

frm, frm_msg_form, frm_sending, lbl, ent = {}, {}, {}, {}, {}

# Вкладка email-сообщений =============================================================================
frm['email'] = tk.Frame(notebook, bg=THEME_COLOR, width=400, )

# === Фрейм №1 - формы сообщения ===
frm_msg_form['email'], lbl['email'], ent['email'] = tk.Frame(frm['email'], bg=THEME_COLOR, width=400, ), {}, {}
# Описание раздела
lbl['email']['description'] = tk.Label(frm_msg_form['email'], bg=THEME_COLOR, text='Запись в базу данных e-mail сообщений', 
                                        font=('Segoe UI', 10, 'bold'))
# Виджеты форм сообщения
lbl['email']['to'] = tk.Label(frm_msg_form['email'], bg=THEME_COLOR,
            text = 'Адреса (через ;):', width=13, anchor='w', )
ent['email']['to'] = tk.Entry(frm_msg_form['email'], width=72, highlightthickness=1, highlightcolor = "Gainsboro", )
lbl['email']['subj'] = tk.Label(frm_msg_form['email'], bg=THEME_COLOR,
            text = 'Тема:', width=13, anchor='w', )
ent['email']['subj'] = tk.Entry(frm_msg_form['email'], width=72, highlightthickness=1, highlightcolor = "Gainsboro", )
ent['email']['text'] = tk.Text(frm_msg_form['email'], width=90, height=3, highlightthickness=1, highlightcolor = "Gainsboro", 
                                font=((TK_FONT, 9)))

# === Фрейм №2 - кнопка отправки и информационные сообщения ===
frm_sending['email'] = tk.Frame(frm['email'], bg=THEME_COLOR, width=400, )

btn_send, lbl_msg_send = {}, {}
btn_send['email'] = tk.Button(frm_sending['email'], text='Записать в БД', width = 15, 
        command=lambda: loop_msg_service.create_task(btn_email_insert_db_click()))
lbl_msg_send['email'] = tk.Label(frm_sending['email'], text='', 
        bg=THEME_COLOR, width = 45, anchor='w', )


# === Фрейм №3 - шапка отправленных сообщений ===
frm_sent_msg_header, lbl_header_title, btn_prev, btn_next = {}, {}, {}, {}

frm_sent_msg_header['email'] = tk.Frame(frm['email'], width=400, height=280, )
lbl_header_title['email'] = tk.Label(frm_sent_msg_header['email'], bg=THEME_COLOR, text='База данных e-mail сообщений', 
                                        font=('Segoe UI', 10, 'bold'))
btn_prev['email'] = tk.Button(frm_sent_msg_header['email'], text='<', width = 15, 
                    command=lambda: loop_msg_service.create_task(btn_slice_msg_click('email', 'prev')))
btn_next['email'] = tk.Button(frm_sent_msg_header['email'], text='<', width = 15, 
                    command=lambda: loop_msg_service.create_task(btn_slice_msg_click('email', 'next')))

# === Фрейм №4 - просмотр отправленных сообщений ===
frm_sent_messages, lbl_message = {}, {}

frm_sent_messages['email'] = tk.Frame(frm['email'], width=400, height=280, )
lbl_message['email'] = tk.Label(frm_sent_messages['email'], bg=THEME_COLOR, text='Message 1', 
                                        font=('Segoe UI', 10))



# Вкладка telegram-сообщений =============================================================================
frm['telegram'] = tk.Frame(notebook, bg=THEME_COLOR, width=400, )

# === Фрейм №1 - формы сообщения ===
frm_msg_form['telegram'], lbl['telegram'], ent['telegram'] = tk.Frame(frm['telegram'], bg=THEME_COLOR, width=400, ), {}, {}
# Описание раздела
lbl['telegram']['description'] = tk.Label(frm_msg_form['telegram'], bg=THEME_COLOR, text='Запись в базу данных telegram сообщений', 
                                        font=('Segoe UI', 10, 'bold'))
# Виджеты форм сообщения
lbl['telegram']['entity'] = tk.Label(frm_msg_form['telegram'], bg=THEME_COLOR,
            text = 'Тип получателя:', width=13, anchor='w', )
ent['telegram']['entity'] = tk.Entry(frm_msg_form['telegram'], width=72, highlightthickness=1, highlightcolor = "Gainsboro", )
lbl['telegram']['to'] = tk.Label(frm_msg_form['telegram'], bg=THEME_COLOR,
            text = 'Кому:', width=13, anchor='w', )
ent['telegram']['to'] = tk.Entry(frm_msg_form['telegram'], width=72, highlightthickness=1, highlightcolor = "Gainsboro", )
ent['telegram']['text'] = tk.Text(frm_msg_form['telegram'], width=90, height=3, highlightthickness=1, highlightcolor = "Gainsboro", 
                                font=((TK_FONT, 9)))

# === Фрейм №2 - кнопка отправки и информационные сообщения ===
frm_sending['telegram'] = tk.Frame(frm['telegram'], bg=THEME_COLOR, width=400, )

btn_send['telegram'] = tk.Button(frm_sending['telegram'], text='Записать в БД', width = 15, 
        command=lambda: loop_msg_service.create_task(btn_telegram_insert_db_click()))
lbl_msg_send['telegram'] = tk.Label(frm_sending['telegram'], text='', 
        bg=THEME_COLOR, width = 45, anchor='w', )


loop_msg_service = asyncio.get_event_loop()
loop_msg_service.run_until_complete(show_send_msg())