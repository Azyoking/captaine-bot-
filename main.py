import discord
from discord.ext import commands, tasks
from discord.ui import Button, View
import random
import asyncio

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

# -- CONFIG -- (Remplace avec tes IDs) --
TOKEN = "MTM4NDQ3ODk5ODYyMDQwOTg5OQ.GKIvj6.KErE5mJMdqR94YF-SUPhzOl9Irj72iWPybNvRs"

# Salons
LEADERBOARD_CHANNEL_ID = 1384529976933748816  # salon leaderboard
ANNOUNCE_CHANNEL_ID = 1384525419520327851  # salon annonces générales (reset saison, tournoi, etc)
MATCH_ANNOUNCE_CHANNEL_ID = 1384526358343979149 # salon annonces matchs

# Roles rangs (mets les IDs)
RANK_ROLES = {
 "E-": 1384536378334773308,
    "E": 1384536456558805052,
    "E+": 1384536520077217792,
    "D-": 1384536582647713875,
    "D": 1384536702223253554,
    "D+": 1384536789661909094,
    "C-": 1384536847874527242,
    "C": 1384536915851874335,
    "C+": 1384537016519360634,
    "B-": 1384537081153585224,
    "B": 1384537203631456367,
    "B+": 1384537271222665330,
    "A-": 1384537346484998176,
    "A": 1384537442866172046,
    "A+": 1384537565993898044,
    "S-": 1384537588601458698,
    "S": 1384537665780846602,
    "S+": 1384537917321641985,
    "Z": 1384537979975893124
}

TOURNOI_ROLE_ID = 1384536219660062832  # rôle spécial tournoi

# -- FIN CONFIG --

# Stockage en mémoire (à remplacer par base de données si besoin)
players = {}  # player_id : { 'wins': int, 'losses': int, 'draws': int, 'rank': str }
tournament_players = set()
tournament_type = None  # "1v1", "2v2", "3v3"
tournament_started = False
tournament_poules = {}  # poule_name: [player_ids]
tournament_points = {}  # player_id : points in poule phase

# RANK LIST pour monter/descendre
rank_order = ["E-", "E", "E+", "D-", "D", "D+", "C-", "C", "C+", "B-", "B", "B+", "A-", "A", "A+", "S-", "S", "S+", "Z"]

# Helpers

async def announce_everyone(channel, message):
    await channel.send(f"@everyone {message}")

def get_next_rank(current_rank, up=True):
    try:
        idx = rank_order.index(current_rank)
        if up and idx + 1 < len(rank_order):
            return rank_order[idx + 1]
        elif not up and idx - 1 >= 0:
            return rank_order[idx - 1]
        else:
            return current_rank
    except:
        return "E-"  # default rank if unknown

async def update_rank_role(member, new_rank):
    # Remove all rank roles and add new one
    for r in RANK_ROLES.values():
        if discord.utils.get(member.roles, id=r):
            await member.remove_roles(discord.Object(id=r))
    # Add new rank role
    role = discord.Object(id=RANK_ROLES[new_rank])
    await member.add_roles(role)

def reset_player_data():
    global players
    players = {}

def reset_tournament_data():
    global tournament_players, tournament_type, tournament_started, tournament_poules, tournament_points
    tournament_players = set()
    tournament_type = None
    tournament_started = False
    tournament_poules = {}
    tournament_points = {}

def leaderboard_sorted():
    # Tri par victoires DESC, défaites ASC, égalités ASC
    return sorted(players.items(), key=lambda x: (-x[1]['wins'], x[1]['losses'], x[1]['draws']))

async def update_leaderboard():
    channel = bot.get_channel(LEADERBOARD_CHANNEL_ID)
    if not channel:
        return
    leaderboard = leaderboard_sorted()
    embed = discord.Embed(title="Leaderboard Captain Fighter", color=discord.Color.blue())
    desc = ""
    rank_num = 1
    for player_id, data in leaderboard:
        user = await bot.fetch_user(player_id)
        desc += f"**{rank_num}.** {user.name} - Rank: {data['rank']} | W: {data['wins']} | L: {data['losses']} | D: {data['draws']}\n"
        rank_num += 1
    embed.description = desc if desc else "Aucun joueur enregistré."
    await channel.purge(limit=10)
    await channel.send(embed=embed)

# Commandes et Events

@bot.event
async def on_ready():
    print(f"Bot connecté en tant que {bot.user}")

# INSCRIPTION TOURNOI (avec boutons)

class InscriptionTournoiView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.inscribed_users = set()

    @discord.ui.button(label="S'inscrire", style=discord.ButtonStyle.green)
    async def inscrire(self, interaction: discord.Interaction, button: Button):
        member = interaction.user
        role = interaction.guild.get_role(TOURNOI_ROLE_ID)
        if role in member.roles:
            await interaction.response.send_message("Tu es déjà inscrit au tournoi.", ephemeral=True)
            return
        await member.add_roles(role)
        tournament_players.add(member.id)
        await interaction.response.send_message("Inscription réussie au tournoi !", ephemeral=True)

    @discord.ui.button(label="Se désinscrire", style=discord.ButtonStyle.red)
    async def desinscrire(self, interaction: discord.Interaction, button: Button):
        member = interaction.user
        role = interaction.guild.get_role(TOURNOI_ROLE_ID)
        if role not in member.roles:
            await interaction.response.send_message("Tu n'es pas inscrit au tournoi.", ephemeral=True)
            return
        await member.remove_roles(role)
        tournament_players.discard(member.id)
        await interaction.response.send_message("Désinscription réussie.", ephemeral=True)

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.grey)
    async def annuler(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()

@bot.command()
@commands.has_permissions(administrator=True)
async def tournoi_inscription(ctx):
    """Message avec boutons inscription tournoi"""
    view = InscriptionTournoiView()
    await ctx.send("Clique sur un bouton pour t'inscrire ou te désinscrire au tournoi :", view=view)

@bot.command()
@commands.has_permissions(administrator=True)
async def start_tournament(ctx, type_tournament: str):
    """Démarrer tournoi : 1v1, 2v2 ou 3v3"""
    global tournament_type, tournament_started, tournament_players, tournament_poules, tournament_points

    if tournament_started:
        await ctx.send("Un tournoi est déjà en cours.")
        return

    if type_tournament not in ["1v1", "2v2", "3v3"]:
        await ctx.send("Type de tournoi invalide. Choisis parmi : 1v1, 2v2, 3v3")
        return

    if len(tournament_players) < int(type_tournament[0]) * 2:
        await ctx.send(f"Pas assez de joueurs pour un tournoi {type_tournament}. Inscrivez-vous plus nombreux !")
        return

    tournament_type = type_tournament
    tournament_started = True

    await announce_everyone(bot.get_channel(ANNOUNCE_CHANNEL_ID), f"Le tournoi {tournament_type} commence ! Préparez-vous !")

    # Tirage au sort poules (4 joueurs par poule max)
    players_list = list(tournament_players)
    random.shuffle(players_list)

    # Construction poules
    poule_size = 4
    tournament_poules = {}
    poule_num = 1
    for i in range(0, len(players_list), poule_size):
        poule_players = players_list[i:i+poule_size]
        tournament_poules[f"Poule {poule_num}"] = poule_players
        poule_num += 1

    # Init points poules
    tournament_points = {pid: 0 for pid in tournament_players}

    # Affiche poules en message embed
    embed = discord.Embed(title=f"Poule du tournoi {tournament_type}", color=discord.Color.gold())
    for poule_name, pids in tournament_poules.items():
        names = []
        for pid in pids:
            user = await bot.fetch_user(pid)
            names.append(user.name)
        embed.add_field(name=poule_name, value="\n".join(names), inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def leaderboard(ctx):
    """Afficher le leaderboard"""
    leaderboard = leaderboard_sorted()
    embed = discord.Embed(title="Leaderboard Captain Fighter", color=discord.Color.blue())
    desc = ""
    rank_num = 1
    for player_id, data in leaderboard:
        user = await bot.fetch_user(player_id)
        desc += f"**{rank_num}.** {user.name} - Rank: {data['rank']} | W: {data['wins']} | L: {data['losses']} | D: {data['draws']}\n"
        rank_num += 1
    if desc == "":
        desc = "Aucun joueur enregistré."
    embed.description = desc
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def reset_season(ctx):
    """Reset complet saison"""
    reset_player_data()
    reset_tournament_data()
    announce_channel = bot.get_channel(ANNOUNCE_CHANNEL_ID)
    await announce_everyone(announce_channel, "La saison a été réinitialisée ! Tous les scores et ranks sont remis à zéro. Préparez-vous pour une nouvelle saison de folie ! 🔥")

@bot.command()
@commands.has_permissions(administrator=True)
async def setmatchrank(ctx, winner: discord.Member, loser: discord.Member):
    """Enregistrer un match classé et gérer ranks"""
    global players
    if winner.id not in players:
        players[winner.id] = {"wins":0,"losses":0,"draws":0,"rank":"E-"}
    if loser.id not in players:
        players[loser.id] = {"wins":0,"losses":0,"draws":0,"rank":"E-"}
    
    players[winner.id]["wins"] += 1
    players[loser.id]["losses"] += 1

    # Gestion ranks
    winner_rank = players[winner.id]["rank"]
    loser_rank = players[loser.id]["rank"]

    new_winner_rank = get_next_rank(winner_rank, up=True)
    new_loser_rank = get_next_rank(loser_rank, up=False)

    players[winner.id]["rank"] = new_winner_rank
    players[loser.id]["rank"] = new_loser_rank

    # Update roles
    await update_rank_role(winner, new_winner_rank)
    await update_rank_role(loser, new_loser_rank)

    # Annonce match
    channel = bot.get_channel(MATCH_ANNOUNCE_CHANNEL_ID)
    await channel.send(f"{winner.mention} a gagné contre {loser.mention} ! 🎉 {winner.name} passe {new_winner_rank} et {loser.name} descend à {new_loser_rank}.")

    # Update leaderboard
    await update_leaderboard()

@bot.command()
@commands.has_permissions(administrator=True)
async def reset_leaderboard(ctx):
    """Reset uniquement stats joueurs (victoires, défaites, égalités), rank aussi remis à E-"""
    global players
    for pid in players:
        players[pid]["wins"] = 0
        players[pid]["losses"] = 0
        players[pid]["draws"] = 0
        players[pid]["rank"] = "E-"

    # Remove all rank roles and re-add E- to everyone who is tracked
    guild = ctx.guild
    for pid in players:
        member = guild.get_member(pid)
        if member:
            await update_rank_role(member, "E-")

    await ctx.send("Le leaderboard a été reset. Tous les joueurs sont remis à 0 et au rang E-.")
    await update_leaderboard()

# Ajoute d'autres commandes de gestion tournoi, match, inscriptions, etc... selon besoins

bot.run(TOKEN)
