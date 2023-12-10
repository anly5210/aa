from openai import OpenAI
import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
import openai
import random
import time
import asyncio
from colorama import init, Fore
import io
from io import BytesIO
import requests
from PIL import Image
import base64

# Load environment variables
load_dotenv()

# Initialize the OpenAI client with your API key
openai_api_key = os.getenv("OPENAI_API_KEY")
if openai_api_key is None:
    raise ValueError("No OpenAI API key found. Make sure to set the OPENAI_API_KEY environment variable.")
client = OpenAI(api_key=openai_api_key)
openai.api_key = openai_api_key

# Initialize Discord intents and bot
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Initialize colorama for colored console output
init()

# Rate limiting
RATE_LIMIT = 0.5

# Get behavior settings from .env
chatgpt_behaviour = os.getenv("BEHAVIOUR")

# Determine if the bot should respond to the message
def should_bot_respond_to_message(message):
    channel_ids_str = os.getenv("CHANNEL_IDS")
    if not channel_ids_str:
        return False, False

    allowed_channel_ids = [int(channel_id) for channel_id in channel_ids_str.split(',')]
    if message.author == bot.user:
        return False, False

    # Check for bot's own 'Generated Image' messages
    if "Generated Image" in message.content:
        return False, False

    is_random_response = random.random() < 0.01
    mentioned_users = [user for user in message.mentions if not user.bot]
    if mentioned_users or not (bot.user in message.mentions or is_random_response or message.channel.id in allowed_channel_ids):
        return False, False

    return (bot.user in message.mentions or is_random_response or message.channel.id in allowed_channel_ids), is_random_response


# Split message into chunks
def split_message(message_content, min_length=1500):
    chunks = []
    remaining = message_content
    while len(remaining) > min_length:
        chunk = remaining[:min_length]
        last_punctuation_index = max(chunk.rfind("."), chunk.rfind("!"), chunk.rfind("?"))
        if last_punctuation_index == -1:
            last_punctuation_index = min_length - 1
        chunks.append(chunk[:last_punctuation_index + 1])
        remaining = remaining[last_punctuation_index + 1:]
    chunks.append(remaining)
    return chunks

async def async_chat_completion(*args, **kwargs):
    return await asyncio.to_thread(openai.chat.completions.create, *args, **kwargs)

async def fetch_message_history(channel):
    history_length_str = os.getenv("HISTORYLENGTH")
    history_length = int(history_length_str) if history_length_str else 15  # default to 100 if not set

    message_history = []
    async for message in channel.history(limit=history_length):
        if message.embeds:
            continue
        if "Generated Image" in message.content or message.content.startswith('!generate'):
            continue
        if message.content.startswith('!generate'):
            continue
        role = "assistant" if message.author.bot else "user"
        message_history.append({"role": role, "content": message.content})

    return message_history[::-1] if message_history else []

async def encode_discord_image(image_url):
    response = requests.get(image_url)
    image = Image.open(io.BytesIO(response.content))
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

async def analyze_image(base64_image, instructions):
    payload = {
        "model": "gpt-4-vision-preview",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instructions},  # Use the instructions provided in the message
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }
        ],
        "max_tokens": 300
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {openai_api_key}"
    }

    response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
    return response.json()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')

@bot.command()
async def generate(ctx, *, prompt: str):
    try:
        print(f"Creating image based on: {prompt}")
        async with ctx.typing():
            response = client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size="1024x1024",
                quality="standard",
                n=1,
            )
            image_url = response.data[0].url
            image_data = requests.get(image_url).content
            image_file = BytesIO(image_data)
            image_file.seek(0)
            image_discord = discord.File(fp=image_file, filename='image.png')

        await ctx.send(f"Generated Image -- every image you generate costs $0.04 so please keep that in mind\nPrompt: {prompt}", file=image_discord)

    except openai.BadRequestError as e:
        # Extracting the relevant error message
        error_message = str(e)
        if 'content_policy_violation' in error_message:
            # Find the start and end of the important message
            start = error_message.find("'message': '") + len("'message': '")
            end = error_message.find("', 'param'")
            important_message = error_message[start:end]

            # Send the extracted message to the channel
            await ctx.send(f"Error: {important_message}")

    except Exception as e:
        # Handle other exceptions
        await ctx.send(f"An error occurred: {e}")

@bot.event
async def on_message(message):
    # First, always call this to ensure the bot can process commands
    await bot.process_commands(message)

    # without this, the bot will generate 2 images erroneously
    if message.content.startswith(bot.command_prefix):
        return

    # Check if the message is from the bot itself
    if message.author == bot.user:
        return

    # Initialize instructions variable
    instructions = "What’s in this image?"  # Default instructions

    # Update instructions if there is accompanying text
    if message.content and message.author != bot.user:
        instructions = message.content

    # Process image attachments
    if message.attachments:
        for attachment in message.attachments:
            if attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg','.webp')):
                async with message.channel.typing():
                    base64_image = await encode_discord_image(attachment.url)
                    instructions = message.content if message.content else "What’s in this image?"
                    analysis_result = await analyze_image(base64_image, instructions)
                    response_text = analysis_result.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if response_text:
                        await message.channel.send(response_text)
                        # Using a different color for the actual analysis result
                        print(Fore.BLUE + "Image analysis result: " + Fore.YELLOW + f"{response_text}")
                    else:
                        response_fail_message = "Sorry, I couldn't analyze the image."
                        await message.channel.send(response_fail_message)
                        # Using a different color for failure messages
                        print(Fore.RED + response_fail_message)
                    return

    await bot.process_commands(message)
    
    should_respond, is_random_response = should_bot_respond_to_message(message)
    if should_respond:
        airesponse_chunks = []
        response = {}
        openai_api_error_occurred = False

        try:
            channel = message.channel
            async with channel.typing():
                messages = await fetch_message_history(channel)
                messages = [
                               {"role": "system", "content": chatgpt_behaviour},
                               {"role": "user", "content": "Here is the message history:"}
                           ] + messages
                messages += [{"role": "assistant", "content": "What is your reply?"}, {"role": "system", "content": chatgpt_behaviour}]
                
                print('Chat history:')
                for msg in messages:
                    role = msg['role']
                    content = msg['content'].replace('\n', '\n               ')
                    print(f'  {role.capitalize()}: {content}')
                
                if is_random_response:
                    max_tokens = int(os.getenv("MAX_TOKENS_RANDOM"))
                else:
                    max_tokens = int(os.getenv("MAX_TOKENS"))

                response = await async_chat_completion(
                    model=os.getenv("MODEL_CHAT"),
                    messages=messages,
                    temperature=1.5,
                    top_p=0.9,
                    max_tokens=max_tokens
                )
                airesponse = response.choices[0].message.content
                airesponse_chunks = split_message(airesponse)
                total_sleep_time = RATE_LIMIT * len(airesponse_chunks)
                await asyncio.sleep(total_sleep_time)
  
          # New: Check if the message has an image attachment
                if message.attachments:
                    for attachment in message.attachments:
                        if any(attachment.filename.lower().endswith(ext) for ext in ['jpg', 'jpeg', 'png']):
                            await message.channel.send("Analyzing image, please wait...")
                            base64_image = await encode_discord_image(attachment.url)
                            analysis_result = await analyze_image(base64_image)
                            response_text = analysis_result.get("choices", [{}])[0].get("message", {}).get("content", "")
                            await message.channel.send(f"Image analysis result: {response_text}")
                            break
  
        except openai.OpenAIError as e:
            print(f"Error: OpenAI API Error - {e}")
            airesponse = f"An error has occurred with your request. Please try again. Error details: {e}"
            openai_api_error_occurred = True
            await message.channel.send(airesponse)

        except Exception as e:
            print(Fore.BLUE + f"Error: {e}" + Fore.RESET)
            airesponse = "Wuh?"

        if not openai_api_error_occurred:
            for chunk in airesponse_chunks:
                await message.channel.send(chunk)
                print(bot.user, ":", Fore.RED + chunk + Fore.RESET)
                time.sleep(RATE_LIMIT)

        if 'usage' in response:
            print("Total Tokens:", Fore.GREEN + str(response["usage"]["total_tokens"]) + Fore.RESET)
  

# Run the bot with your token
discord_bot_token = os.getenv("DISCORD_TOKEN")
if discord_bot_token is None:
    raise ValueError("No Discord bot token found. Make sure to set the DISCORD_BOT_TOKEN environment variable.")
bot.run(discord_bot_token)
