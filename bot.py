import discord
from discord.ext import commands
import os

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Stores active hosted sessions: {channel_id: {"vc": vc, "role": role, "host": member}}
active_sessions = {}

HOSTING_CHANNEL_NAME = "hosting"  # The text channel where !host is used


class JoinView(discord.ui.View):
    def __init__(self, role: discord.Role, vc: discord.VoiceChannel):
        super().__init__(timeout=None)
        self.role = role
        self.vc = vc

    @discord.ui.button(label="Join Game Night", style=discord.ButtonStyle.green, emoji="🎮")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if self.role in member.roles:
            await interaction.response.send_message(
                "You already have access! Head to the voice channel.", ephemeral=True
            )
            return
        await member.add_roles(self.role)
        await interaction.response.send_message(
            f"✅ You're in! Join **{self.vc.name}** to play.", ephemeral=True
        )

    @discord.ui.button(label="Leave", style=discord.ButtonStyle.red, emoji="🚪")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if self.role not in member.roles:
            await interaction.response.send_message("You're not in this session.", ephemeral=True)
            return
        await member.remove_roles(self.role)
        # Disconnect from VC if they're in it
        if member.voice and member.voice.channel == self.vc:
            await member.move_to(None)
        await interaction.response.send_message("You've left the game night.", ephemeral=True)


@bot.event
async def on_ready():
    print(f"Bot is online as {bot.user}")


@bot.command(name="host")
async def host(ctx, *, game_name: str = None):
    if ctx.channel.name != HOSTING_CHANNEL_NAME:
        await ctx.send(f"Use `!host` in #{HOSTING_CHANNEL_NAME}.", delete_after=5)
        return

    if not game_name:
        await ctx.send("Please provide a game name. Example: `!host Minecraft`", delete_after=5)
        return

    guild = ctx.guild
    host_member = ctx.author

    # Create a temporary role for this session
    role = await guild.create_role(name=f"🎮 {game_name} Night")

    # Find a category to put the VC in (optional: create one called Game Night)
    category = discord.utils.get(guild.categories, name="🔊  voice channels")

    # Set permissions: hidden from everyone, visible to role holders
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        role: discord.PermissionOverwrite(view_channel=True, connect=True, speak=True),
        host_member: discord.PermissionOverwrite(view_channel=True, connect=True, speak=True, move_members=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True),
    }

    vc = await guild.create_voice_channel(
        name=f"🎮 {game_name}",
        overwrites=overwrites,
        category=category,
    )

    # Give the host the role too
    await host_member.add_roles(role)

    # Store session keyed by host's id
    active_sessions[host_member.id] = {
        "vc": vc,
        "role": role,
        "game": game_name,
        "embed_message": None,
    }

    embed = discord.Embed(
        title=f"🎮 Game Night — {game_name}",
        description=(
            f"**Host:** {host_member.mention}\n"
            f"**Voice Channel:** {vc.mention}\n\n"
            "Click **Join Game Night** to get access to the voice channel.\n"
            "Click **Leave** to remove yourself."
        ),
        color=discord.Color.purple(),
    )
    embed.set_footer(text=f"Host: type !closehost when you're done to close the session.")

    view = JoinView(role=role, vc=vc)
    msg = await ctx.send(embed=embed, view=view)
    active_sessions[host_member.id]["embed_message"] = msg

    # Delete the original command message to keep channel tidy
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.command(name="closehost")
async def closehost(ctx):
    host_member = ctx.author
    session = active_sessions.get(host_member.id)

    if not session:
        await ctx.send("You don't have an active hosted session.", delete_after=5)
        return

    vc = session["vc"]
    role = session["role"]
    game = session["game"]
    embed_message = session["embed_message"]

    # Move everyone out of the VC before deleting
    for member in vc.members:
        try:
            await member.move_to(None)
        except Exception:
            pass

    # Delete VC and role
    await vc.delete(reason="Host closed the session")
    await role.delete(reason="Host closed the session")

    # Edit the original embed to show closed
    if embed_message:
        closed_embed = discord.Embed(
            title=f"🔒 Game Night Closed — {game}",
            description=f"The session hosted by {host_member.mention} has ended. Thanks for playing!",
            color=discord.Color.greyple(),
        )
        await embed_message.edit(embed=closed_embed, view=None)

    del active_sessions[host_member.id]

    await ctx.send(f"✅ Session closed. The voice channel has been removed.", delete_after=8)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.event
async def on_voice_state_update(member, before, after):
    """Auto-close VC if host leaves and it's empty."""
    for host_id, session in list(active_sessions.items()):
        vc = session["vc"]
        if before.channel == vc and len(vc.members) == 0:
            # VC is now empty — leave it open, host must !closehost manually
            # (auto-close would be annoying if everyone steps out briefly)
            pass


bot.run(os.environ["DISCORD_TOKEN"])
