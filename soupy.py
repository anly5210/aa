from dotenv import load_dotenv
import os
import discord
from discord.ext import commands
import openai
import random
import time
from colorama import init, Fore
import re

# enable colors in windows cmd console
init(convert=True)

# Load environment variables
load_dotenv()

# rate limit in seconds (sleep this many seconds between each OpenAI API request)
RATE_LIMIT = 1.0
openai.api_key = os.environ.get("OPENAI_API_KEY")

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix='!', intents=discord.Intents.all())
chatgpt_behaviour = os.environ.get("BEHAVIOUR")
messages = []

# The bot will respond whenever it is @mentioned, and also in whatever channel is specified in .env CHANNEL_ID.  It will respond in that channel even when it is not mentioned.
def should_bot_respond_to_message(message):
    if message.author == bot.user:
        return False
    return (bot.user in message.mentions or random.random() < 0.02 or
            message.channel.id == int(os.environ.get("CHANNEL_ID")))

# Split message into multiple chunks of at least min_length characters
def split_message(message_content, min_length=1500):
    chunks = []
    remaining = message_content
    while len(remaining) > min_length:
        chunk = remaining[:min_length]
        last_period_index = chunk.rfind(".")
        if last_period_index == -1:
            last_period_index = min_length - 1
        chunks.append(chunk[:last_period_index+1])
        remaining = remaining[last_period_index+1:]
    chunks.append(remaining)
    return chunks

@bot.event
async def on_message(message):
    if should_bot_respond_to_message(message):
        try:
            # Get the channel object from the message object
            channel = message.channel

            # Retrieve the last 10 messages from the channel history
            messages = []
            async for message in channel.history(limit=int(os.environ.get("HISTORYLENGTH"))):
                messages.append({"role": "system", "content": message.content})
            messages = messages[::-1]

            # Append the messages to the chat history
            messages = [
                {"role": "user", "content": chatgpt_behaviour},
                {"role": "system", "content": "Here are the last 10 messages"}
            ] + messages
            messages += [{"role": "system", "content": "What is your reply?"}]

            print(f'invoking openapi with messages: {messages}')
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=1.5,
                top_p=0.9,
                max_tokens=int(os.environ.get("MAX_TOKENS"))
            )
            airesponse = (response.choices[0].message.content)
        except openai.error.ApiError as e:
            print(f"Error: OpenAI API Error - {e}")
            airesponse = "OpenAI API Error -- there is a problem with OpenAI's services right now."
        except Exception as e:
            print(Fore.BLUE + f"Error: {e}" + Fore.RESET)
            airesponse = "Wuh?"

        # Split response into multiple messages if it is longer than 1000 characters
        airesponse_chunks = split_message(airesponse)

        # Send each message individually
        for chunk in airesponse_chunks:
            await message.channel.send(chunk)
            print(bot.user, ":", Fore.RED + chunk + Fore.RESET)
            time.sleep(RATE_LIMIT)  # rate limit on OpenAI queries

        print("Total Tokens:", Fore.GREEN + str(
            response["usage"]["total_tokens"]) + Fore.RESET)  # displays total tokens used in the console


bot.run(os.environ.get("DISCORD_TOKEN"))