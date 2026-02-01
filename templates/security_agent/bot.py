import discord
import os
from dotenv import load_dotenv
from agent import AgentOrchestrator

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# Initialize the Brain
brain = AgentOrchestrator()

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    # 1. Handle File Attachments (Trigger)
    if message.attachments:
        for attachment in message.attachments:
            await message.channel.send(f"🤖 **Sentinel:** I see a file. Analyzing `{attachment.filename}`...")
            
            file_bytes = await attachment.read()
            # Run blocking task
            result = brain.handle_file_upload(attachment.filename, file_bytes)
            
            await send_discord_report(message.channel, result)
        return

    # 2. Handle Text/URL (Orchestration)
    # We only trigger if explicitly mentioned or in DM to save API costs
    if client.user in message.mentions or isinstance(message.channel, discord.DMChannel):
        user_text = message.content.replace(f'<@{client.user.id}>', '').strip()
        
        await message.channel.send("🤖 **Sentinel:** Processing...")
        
        # The Orchestrator decides if it's a URL scan or chat
        result = brain.handle_text_input(user_text)
        
        if result["type"] == "chat":
            await message.channel.send(result["message"])
        else:
            await send_discord_report(message.channel, result)

async def send_discord_report(channel, result):
    # Send the LLM written summary
    text_response = f"**🛡️ Security Report for {result['target']}**\n\n{result['summary']}"
    
    # Send PDF
    file = discord.File(result['pdf'], filename="report.pdf")
    await channel.send(content=text_response, file=file)
    
    # Cleanup
    os.remove(result['pdf'])

client.run(os.getenv("DISCORD_TOKEN"))
