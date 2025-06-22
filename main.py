import asyncio
import re
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, BufferedInputFile, BotCommand
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram import F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

API_TOKEN = "ur_token"

bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
)
dp = Dispatcher()

search_results = {}
user_likes = {}
dp["waiting_for_search_input"] = False
dp["waiting_for_username"] = False

#Markdown escaping function
def escape_markdown(text):
    escape_chars = r"\\*_`[]()~>#+-=|{}.!<>"
    return ''.join(f"\\{c}" if c in escape_chars else c for c in text)

async def set_main_menu():
    await bot.set_my_commands([
        BotCommand(command="/start", description="Start bot"),
        BotCommand(command="/search", description="Search on SoundCloud"),
        BotCommand(command="/likes", description="Get user's liked tracks")
    ])

def clean_filename(title):
    title = title.replace('\\', '⧵')
    return re.sub(r'[/:*?"<>|]', '', title)[:64]

async def download_track(url):
    cmd = [
        'yt-dlp',
        '-x', '--audio-format', 'mp3',
        '-o', '-',
        '--quiet',
        url
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    return stdout

async def yt_search(query):
    cmd = [
        'yt-dlp',
        f'scsearch10:{query}',
        '--print', 'id',
        '--print', 'title',
        '--print', 'webpage_url',
        '--no-warnings',
        '--quiet'
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    lines = stdout.decode().splitlines()
    return [
        (lines[i], lines[i + 1], lines[i + 2])
        for i in range(0, len(lines), 3)
        if i + 2 < len(lines)
    ]

async def get_user_likes(username: str):
    cmd = [
        'yt-dlp',
        f'https://soundcloud.com/{username}/likes',
        '--get-title',
        '--get-url',
        '--max-downloads', '50',
        '--quiet',
        '--no-warnings'
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    lines = stdout.decode().splitlines()
    return [(lines[i], lines[i + 1]) for i in range(0, len(lines), 2) if i + 1 < len(lines)]

def build_likes_keyboard(tracks, page=0, per_page=10):
    builder = InlineKeyboardBuilder()
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, len(tracks))
    for idx in range(start_idx, end_idx):
        title, url = tracks[idx]
        builder.button(
            text=f"{idx + 1}. {title[:30]}",
            callback_data=f"download_{idx}"
        )
    builder.adjust(1)
    pagination_row = []
    if page > 0:
        pagination_row.append(InlineKeyboardButton(text="⬅️ Back", callback_data=f"likes_prev_{page}"))
    if end_idx < len(tracks):
        pagination_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"likes_next_{page}"))
    if pagination_row:
        builder.row(*pagination_row)
    return builder.as_markup()

@dp.message(Command(commands=["start"]))
async def cmd_start(message: types.Message):
    await message.answer("**🔍 Hi! Use /search to find music or /likes to view likes.**")

@dp.message(Command(commands=["search"]))
async def search_command_handler(message: types.Message):
    dp["waiting_for_search_input"] = True
    await message.answer("**🔎 Enter song name to search on SoundCloud:**")

@dp.message(Command(commands=["likes"]))
async def likes_handler(message: types.Message):
    dp["waiting_for_username"] = True
    await message.answer("**👤 Enter SoundCloud username to view likes:**")

@dp.message(F.text & ~F.command)
async def handle_text_input(message: types.Message):
    if dp.get("waiting_for_search_input"):
        dp["waiting_for_search_input"] = False
        await process_search(message)
    elif dp.get("waiting_for_username"):
        dp["waiting_for_username"] = False
        await process_likes(message)

async def process_search(message: types.Message):
    query = message.text.strip()
    if not query:
        await message.answer("**❌ Please enter a valid query.**")
        return
    await message.answer("**⌛ Searching...**")
    results = await yt_search(query)
    if not results:
        await message.answer("**❌ Nothing found.**")
        return
    search_results[message.chat.id] = results
    builder = InlineKeyboardBuilder()
    for i, (_, title, _) in enumerate(results):
        builder.button(text=f"{i + 1}. {title[:50]}", callback_data=str(i))
    builder.adjust(1)
    await message.answer("**🎵 Results:**", reply_markup=builder.as_markup())

def easter_egg():
    return "code written by lyricss1 :)"

async def process_likes(message: types.Message):
    username = message.text.strip()
    if not username:
        await message.answer("**❌ Please enter a valid username.**")
        return
    await message.answer(f"**⌛ Getting likes for {username}...**")
    try:
        liked_tracks = await get_user_likes(username)
        if not liked_tracks:
            await message.answer("**❌ No likes found or user doesn't exist.**")
            return
        user_likes[message.chat.id] = {
            'username': username,
            'tracks': liked_tracks,
            'page': 0
        }
        markup = build_likes_keyboard(liked_tracks)
        total_tracks = len(liked_tracks)
        await message.answer(
            f"**❤️ {username}'s likes (1-{min(10, total_tracks)} of {total_tracks}):**",
            reply_markup=markup
        )
    except Exception as e:
        await message.answer(f"**❌ Error getting likes: {str(e)}**")

@dp.callback_query(F.data.startswith("likes_"))
async def handle_likes_pagination(call: types.CallbackQuery):
    data = call.data.split("_")
    direction = data[1]
    current_page = int(data[2])
    user_data = user_likes.get(call.message.chat.id)
    if not user_data:
        await call.answer("Session expired. Please use /likes again.")
        return
    tracks = user_data['tracks']
    new_page = current_page - 1 if direction == "prev" else current_page + 1
    user_data['page'] = new_page
    user_likes[call.message.chat.id] = user_data
    markup = build_likes_keyboard(tracks, new_page)
    start_idx = new_page * 10 + 1
    end_idx = min(start_idx + 9, len(tracks))
    await call.message.edit_text(
        f"**❤️ {user_data['username']}'s likes ({start_idx}-{end_idx} of {len(tracks)}):**",
        reply_markup=markup
    )
    await call.answer()


#title markdn
@dp.callback_query(F.data.startswith("download_"))
async def handle_download_from_likes(call: types.CallbackQuery):
    idx = int(call.data.split("_")[1])
    user_data = user_likes.get(call.message.chat.id)
    if not user_data or idx >= len(user_data['tracks']):
        await call.answer("❌ Error: please try again.")
        return
    title, url = user_data['tracks'][idx]
    safe_title = escape_markdown(title)
    downloading_msg = await call.message.answer(f"**⬇️ Downloading: {safe_title}**")
    try:
        audio_data = await download_track(url)
        if not audio_data:
            await downloading_msg.edit_text("**❌ Download error.**")
            return
        safe_filename = clean_filename(title) + '.mp3'
        audio_file = BufferedInputFile(audio_data, filename=safe_filename)
        await call.message.answer_audio(
            audio_file,
            caption=f"**🎧 {safe_title}**",
            title=title[:64]
        )
        await downloading_msg.delete()
    except Exception as e:
        await downloading_msg.edit_text(f"**❌ Error: {str(e)}**")
    finally:
        await call.answer()

#title markdn2
@dp.callback_query(F.data)
async def send_audio(call: types.CallbackQuery):
    idx = int(call.data)
    results = search_results.get(call.message.chat.id)
    if not results or idx >= len(results):
        await call.answer("❌ Error: please try again.")
        return
    vid, title, url = results[idx]
    safe_title = escape_markdown(title)
    downloading_msg = await call.message.answer(f"**⬇️ Downloading: {safe_title}**")
    try:
        audio_data = await download_track(url)
        if not audio_data:
            await downloading_msg.edit_text("**❌ Download error.**")
            return
        safe_filename = clean_filename(title) + '.mp3'
        audio_file = BufferedInputFile(audio_data, filename=safe_filename)
        await call.message.answer_audio(
            audio_file,
            caption=f"**🎧 {safe_title}**",
            title=title[:64]
        )
        await downloading_msg.delete()
    except Exception as e:
        await downloading_msg.edit_text(f"**❌ Error: {str(e)}**")
    finally:
        await call.answer()

async def main():
    await set_main_menu()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
